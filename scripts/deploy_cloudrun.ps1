# 디벨로직을 Google Cloud Run (서울)에 올린다 — 여러 업체가 주소로 접속하는 시범 서비스.
#   실행: powershell -ExecutionPolicy Bypass -File scripts\deploy_cloudrun.ps1
#   여러 번 실행해도 된다 (이미 있는 것은 건너뛰고 새 코드만 올린다).
#
# 만드는 것 (처음 한 번):
#   - 프로젝트 develogic-pilot (결제 계정 연결)
#   - 자료 보관소 gs://develogic-pilot-data (서울 · 비공개 · 버전 보관): 업체별 자료함, 계정, 설정, 조례 캐시
#   - 서버 전용 서비스 계정: 이 보관소와 운영자 비밀번호만 읽고 쓸 수 있다
#   - 운영자 비밀번호 (Secret Manager operator-password, 무작위). 보기:
#       gcloud secrets versions access latest --secret operator-password --project develogic-pilot
#
# 업체·아이디는 배포 후 웹에서 운영자(아이디 develogic)로 로그인해 [CI 가이드·설정] 화면에서 만든다.
# 최대 1대로 돌린다 (자료를 파일로 저장하므로 서버가 둘이면 서로 덮어쓸 수 있음).
param([string]$Project = 'develogic-pilot')

$ErrorActionPreference = 'Stop'
$gcloud = Join-Path $env:LOCALAPPDATA 'Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd'
if (-not (Test-Path $gcloud)) { $gcloud = 'gcloud' }
$region = 'asia-northeast3'   # 서울
$service = 'develogic'
$bucket = "$Project-data"
$root = Split-Path $PSScriptRoot -Parent

function Test-G([string[]]$a) {   # 있는지 확인만 (없으면 오류가 나도 멈추지 않음)
  $ErrorActionPreference = 'Continue'
  & $gcloud @a 2>$null | Out-Null
  return $LASTEXITCODE -eq 0
}

# 1) 프로젝트 · 결제 · API
if (-not (Test-G @('projects', 'describe', $Project))) {
  & $gcloud projects create $Project --name 'Develogic Pilot'
  if ($LASTEXITCODE -ne 0) { throw "프로젝트 $Project 를 만들지 못했습니다 (이름이 이미 쓰이면 -Project 다른이름)." }
}
$billing = & $gcloud billing projects describe $Project --format 'value(billingEnabled)'
if ($billing -ne 'True') {
  $acct = (& $gcloud billing accounts list --filter 'open=true' --format 'value(name)' | Select-Object -First 1)
  if (-not $acct) { throw '사용할 수 있는 결제 계정이 없습니다.' }
  & $gcloud billing projects link $Project --billing-account $acct | Out-Null
  if ($LASTEXITCODE -ne 0) { throw '결제 계정을 연결하지 못했습니다.' }
}
& $gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com `
  secretmanager.googleapis.com storage.googleapis.com --project $Project
if ($LASTEXITCODE -ne 0) { throw 'API 를 켜지 못했습니다.' }

# 2) 자료 보관소 (서울 · 비공개 · 지우거나 덮어써도 이전 버전 보관)
if (-not (Test-G @('storage', 'buckets', 'describe', "gs://$bucket", '--project', $Project))) {
  & $gcloud storage buckets create "gs://$bucket" --project $Project --location $region `
    --uniform-bucket-level-access --public-access-prevention
  if ($LASTEXITCODE -ne 0) { throw '자료 보관소를 만들지 못했습니다.' }
  & $gcloud storage buckets update "gs://$bucket" --project $Project --versioning | Out-Null
}

# 3) 서버 전용 서비스 계정
$account = "develogic-server@$Project.iam.gserviceaccount.com"
if (-not (Test-G @('iam', 'service-accounts', 'describe', $account, '--project', $Project))) {
  & $gcloud iam service-accounts create develogic-server --project $Project --display-name 'develogic server (data bucket only)' | Out-Null
  Write-Host '서버 전용 서비스 계정을 만들었습니다. 권한이 퍼지도록 잠시 기다립니다...'
  Start-Sleep -Seconds 30
}
& $gcloud storage buckets add-iam-policy-binding "gs://$bucket" --project $Project `
  --member "serviceAccount:$account" --role roles/storage.objectAdmin --quiet | Out-Null
if ($LASTEXITCODE -ne 0) { throw '보관소 권한을 주지 못했습니다.' }

# 4) 운영자 비밀번호 (처음 한 번 무작위로 만들고 화면에는 보여 주지 않는다)
if (-not (Test-G @('secrets', 'describe', 'operator-password', '--project', $Project))) {
  $abc = 'abcdefghjkmnpqrstuvwxyzACDEFGHJKLMNPQRSTUVWXYZ23456789'
  $bytes = New-Object byte[] 16
  [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
  $pw = -join ($bytes | ForEach-Object { $abc[$_ % $abc.Length] })
  $tmp = New-TemporaryFile
  [IO.File]::WriteAllText($tmp, $pw, (New-Object Text.UTF8Encoding $false))
  & $gcloud secrets create operator-password --project $Project --replication-policy automatic --data-file $tmp | Out-Null
  Remove-Item $tmp
  if ($LASTEXITCODE -ne 0) { throw '운영자 비밀번호를 만들지 못했습니다.' }
  Write-Host '운영자 비밀번호를 새로 만들었습니다 (Secret Manager: operator-password).'
}
& $gcloud secrets add-iam-policy-binding operator-password --project $Project `
  --member "serviceAccount:$account" --role roles/secretmanager.secretAccessor --quiet | Out-Null

# 5) 빌드 계정 권한 (새 프로젝트는 Cloud Build 가 기본 계정으로 돌아 권한이 모자랄 수 있다)
$num = & $gcloud projects describe $Project --format 'value(projectNumber)'
foreach ($r in 'roles/cloudbuild.builds.builder', 'roles/run.builder') {
  $ErrorActionPreference = 'Continue'
  & $gcloud projects add-iam-policy-binding $Project --member "serviceAccount:$num-compute@developer.gserviceaccount.com" `
    --role $r --condition None --quiet 2>$null | Out-Null
  $ErrorActionPreference = 'Stop'
}

# 6) 배포
$version = (& git -C $root describe --always --dirty 2>$null)
Write-Host "배포: 프로젝트 $Project · 서울 · 버전 $version"
& $gcloud run deploy $service `
  --source $root `
  --project $Project `
  --region $region `
  --allow-unauthenticated `
  --execution-environment gen2 `
  --min-instances 0 `
  --max-instances 1 `
  --concurrency 40 `
  --timeout 300 `
  --memory 1Gi `
  --cpu 1 `
  --service-account $account `
  --set-env-vars "DEVELOGIC_MULTI=1,DEVELOGIC_DATA=/data,APP_VERSION=$version" `
  --set-secrets 'DEVELOGIC_OPERATOR_PW=operator-password:latest' `
  --add-volume "name=data,type=cloud-storage,bucket=$bucket" `
  --add-volume-mount 'volume=data,mount-path=/data' `
  --quiet
if ($LASTEXITCODE -ne 0) { throw '배포에 실패했습니다.' }

$url = & $gcloud run services describe $service --project $Project --region $region --format 'value(status.url)'
Write-Host ''
Write-Host "접속 주소: $url"
Write-Host '운영자 로그인: 아이디 develogic / 비밀번호 보기 ↓'
Write-Host "  gcloud secrets versions access latest --secret operator-password --project $Project"
