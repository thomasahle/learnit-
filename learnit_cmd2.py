#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

import re, tempfile, subprocess, os, json, textwrap
import itertools, operator, unicodedata
import learnit2
from itertools import starmap
from multiprocessing.pool import ThreadPool
from collections import defaultdict

regsafe = lambda s: re.sub(r'([\-\[\]\/\{\}\(\)\*\+\?\.\\\^\$\|])', r'\\\1', s)

open_cmd = "open"
edit_cmd = "vim"
passwd_file = '.password'
accepted_suffices = ['.pdf', '.java', '.zip']
separator_line = '-' * 50

class Dialog:

   def __init__(self, prefix):
      self.prefix = prefix
      self.help = []
      self.cmds = []
      self.add_command('help', self.__help, 'help', 'Show this message')
      self.add_command('exit|quit|done', self.__exit, 'exit', 'Exit the program')

   def add_command(self, regex, fun, help_cmd, help_text):
      self.help.append((help_cmd, help_text))
      self.cmds.append((re.compile(regex), fun))

   def __help(self):
      print('Supported commands:')
      col_width = max(len(help_cmd) for help_cmd, _ in self.help)
      for help_cmd, help_text in self.help:
         print('  ', help_cmd.ljust(col_width), '-', help_text)

   def __exit(self):
      return True

   def run(self):
      while True:
         cmd = input(self.prefix).strip()
         if not cmd:
            continue
         for (regex, fun) in self.cmds:
            match = regex.match(cmd)
            if match:
               res = fun(*match.groups())
               if res:
                  return
               break
         else:
            print('Unknown command', repr(cmd))


class MainDialog(Dialog):
   def __init__(self, client, cid):
      Dialog.__init__(self, '> ')
      self.add_command('list assignments|la$', self.list_assignments_cmd, 'list assignments', 'List available assignments from courses')
      self.add_command('results?$', self.result_cmd, 'result', 'Number of assignments per group')
      self.cid = cid
      self.client = client
   
   def run(self):
      print('Loading tables...')
      self.tables = client.get_tables(self.cid)
      Dialog.run(self)

   def list_assignments_cmd(self):
      for (aid, title) in sorted(self.tables.assignments):
         print("{}: {}".format(aid, title))

   def result_cmd(self):
      result = defaultdict(list)
      for group in self.tables.groups:
         acc, nac, pen, nos = 0, 0, 0, 0
         for submission in group.submissions:
            if not submission.submit_actions:
               nos += 1
               continue
            actions = submission.grade_actions + submission.submit_actions
            if actions and type(min(actions)) == learnit2.GradeAction:
               if min(actions).grade == learnit2.APPROVED: acc += 1
               if min(actions).grade == learnit2.NOT_APPROVED: nac += 1
               if min(actions).grade == learnit2.NO_GRADE: pen += 1
            if actions and type(min(actions)) == learnit2.SubmitAction:
               pen += 1
         result[acc].append((group, nac, pen, nos))
      for acc, groups in sorted(result.items()):
         print('{} Approves:'.format(acc))
         for group, nac, pen, nos in groups:
            tags = ['{} {}'.format(n,s) for n,s in ((pen,'pending'),(nac,'not approved'),(nos,'not submitted')) if n]
            tagstring = '' if not tags else '({})'.format(', '.join(tags))
            name = group.name if group.name else 'Default Group'
            print(name+':\t', '; '.join(s.person.email for s in group.students), tagstring)
         print()


def login_dialog(client):
   er = learnit.INVALID_PASSWORD
   while er != learnit.SUCCESS:
      username = input('email: ')
      password = input('password: ')
      print('Logging in...')
      data, er = client.login(username, password)
      if er == learnit.INVALID_PASSWORD:
         print("Invalid password!")
   return data


if __name__ == '__main__':
   client = learnit2.Learnit()
   if os.path.exists(passwd_file):
      with open(passwd_file) as f:
         passwd = json.loads(f.read())
      data, er = client.login(passwd['username'], passwd['password'])
   else:
      data = login_dialog(client)
   print('Hello', data[0].name)
   MainDialog(client, '3003023').run()
