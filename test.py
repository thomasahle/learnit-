#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

import unittest, json, learnit

with open('.password') as f:
   password = json.loads(f.read())


class TestErrors(unittest.TestCase):

   def test_login(self):
      client = learnit.Learnit()
      _, er = client.login('bla', 'bla')
      self.assertEqual(er, learnit.INVALID_PASSWORD)

class TestSuccess(unittest.TestCase):

   def setUp(self):
      self.client = learnit.Learnit()
      self.data_my, er = self.client.login(password['username'], password['password'])
      self.assertEqual(er, learnit.SUCCESS)

   def test_info(self):
      name = self.client.get_logininfo(self.data_my)
      self.assertTrue(name.istitle())

   def test_courses(self):
      courses = self.client.list_my_courses(self.data_my)
      self.assertTrue(len(courses) > 0)

   def test_assignments(self):
      courses = self.client.list_my_courses(self.data_my)
      for course_id, title in courses.items():
         assignments = self.client.list_assignments(course_id)
         self.assertEqual(type(assignments), dict)

   def test_table(self):
      assignment_id = next(aid
         for cid in self.client.list_my_courses(self.data_my).keys()
         for aid in self.client.list_assignments(cid).keys())
      groups = self.client.list_submissions(assignment_id)
      self.assertTrue(len(groups) > 10)

   def test_submission(self):
      sub = next(sub
         for cid in self.client.list_my_courses(self.data_my).keys()
         for aid in self.client.list_assignments(cid).keys()
         for row in self.client.list_submissions(aid).values()
         for sub in [self.client.show_submission(aid, row.row)])
      self.assertEqual(type(sub), learnit.Submission)
      self.assertEqual(type(sub.comments), list)

   def test_downloads(self):
      attachment = next(att
         for cid in self.client.list_my_courses(self.data_my).keys()
         for aid in self.client.list_assignments(cid).keys()
         for row in self.client.list_submissions(aid).values()
         for sub in [self.client.show_submission(aid, row.row)]
         for att in self.client.download_attachments(sub.context_id, sub.files))
      self.assertEqual(type(attachment), learnit.Attachment)

   def test_save(self):
      aid, row = next((aid, row.row)
         for cid in self.client.list_my_courses(self.data_my).keys()
         for aid in self.client.list_assignments(cid).keys()
         for row in self.client.list_submissions(aid).values()
         if row.substat == learnit.HAS_SUBMIT)
      sub = self.client.show_submission(aid, row)
      self.assertEqual(sub.sub_status, learnit.HAS_SUBMIT)
      self.assertTrue(len(sub.files) > 0)
      # Change grade
      new_grade = learnit.NO_GRADE if sub.grade != learnit.NO_GRADE else learnit.APPROVED
      er = self.client.save_grade(aid, row, sub.form, new_grade, sub.feedback, sub.grade_to_code)
      self.assertEqual(er, learnit.SUCCESS)
      new_sub = self.client.show_submission(aid, row)
      self.assertEqual(new_sub.grade, new_grade)
      # Change it back
      er = self.client.save_grade(aid, row, sub.form, sub.grade, sub.feedback, new_sub.grade_to_code)
      self.assertEqual(er, learnit.SUCCESS)
      new_new_sub = self.client.show_submission(aid, row)
      self.assertEqual(new_new_sub.grade, sub.grade)
      # Feedback shouldn't change
      self.assertEqual(new_new_sub.feedback, sub.feedback)

   def test_log(self):
      grade_action = next(grade_action
         for cid in self.client.list_my_courses(self.data_my).keys()
         for aid in self.client.list_assignments(cid).keys()
         for grade_action in self.client.get_log(cid, aid))
      self.assertEqual(type(grade_action), learnit.GradeAction)

if __name__ == '__main__':
   unittest.main()
