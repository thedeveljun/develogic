import unittest
from app.engine import run_model
class EngineTests(unittest.TestCase):
 def base(self):return {'project_type':'general_housing','start':'2027-01-01','end':'2027-01-31','opening_cash':0,'loans':[],'events':[]}
 def test_balancing(self):
  p=self.base();p['events']=[{'date':'2027-01-02','type':'equity_in','amount':100},{'date':'2027-01-03','type':'cost','amount':40}]
  self.assertEqual(run_model(p)['months'][0]['closing_cash'],'60')
 def test_limit(self):
  p=self.base();p['loans']=[{'id':'p','limit':10,'annual_rate':0,'day_basis':365}];p['events']=[{'date':'2027-01-02','type':'draw','loan_id':'p','amount':11}]
  with self.assertRaises(ValueError):run_model(p)
 def test_interest(self):
  p=self.base();p['loans']=[{'id':'p','limit':1000,'annual_rate':0.365,'day_basis':365,'payment_day':0}];p['events']=[{'date':'2027-01-01','type':'draw','loan_id':'p','amount':100}]
  # Opening-balance accrual Jan 2-31 = 30 days x 0.1 KRW = 3 KRW.
  self.assertEqual(run_model(p)['months'][0]['interest'],'3')
if __name__=='__main__':unittest.main()
