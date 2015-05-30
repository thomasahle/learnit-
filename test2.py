#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

import unittest, json, learnit2

with open('.password') as f:
   password = json.loads(f.read())


class TestErrors(unittest.TestCase):

   def test_login(self):
      client = learnit2.Learnit()
      _, er = client.login('bla', 'bla')
      self.assertEqual(er, learnit2.INVALID_PASSWORD)

class TestSuccess(unittest.TestCase):

   def setUp(self):
      self.client = learnit2.Learnit()
      res, err = self.client.login(password['username'], password['password'])
      self.assertEqual(err, learnit2.SUCCESS)
      self.person, self.courses = res

   def test_info(self):
      self.assertTrue(self.person.name.istitle())
      self.assertTrue(self.person.id.isdigit())
      self.assertTrue(len(self.courses) > 0)

   def test_tables(self):
      for (cid, title) in self.courses:
         # You can only test for courses where you have certain rights
         if cid == '3003023':
            tables = self.client.get_tables(cid)
            self.assertTrue(tables.groups)
            self.assertTrue(tables.teachers)
            self.assertTrue(tables.students)
            self.assertTrue(tables.submissions)
            self.assertTrue(tables.assignments)
            for assignment in tables.assignments:
               self.assertTrue(len(assignment.title) > 1)
            self.assertTrue(tables.submissions)         
            self.assertEqual(len(tables.teachers), 7)
            self.assertEqual(len(tables.teachers)+len(tables.students), 146)
            self.assertEqual(len(tables.groups), 63)

if __name__ == '__main__':
   unittest.main()
