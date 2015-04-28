# learnit-
Some userscripts for learnit.
Tested with tampermonkey for Chrome.

![screenshot](http://i.imgur.com/csCTEQ8.png)

# learnit_cmd.py
A python command line tool for working with learnit.

<pre>
$ <b>python3 learnit_cmd.py</b>
email: <b>...@itu.dk</b>
password: <b>...</b>
Logging in...
Hello Thomas Dybdahl Ahle!
<br>&gt; <b>help</b>
Supported commands:
   list courses
   list assignments [course_id]
   grade [assignment_id]
   exit
<br>&gt; <b>list courses</b>
You have 1 courses:
0) 3003023: Algorithms and Data Structures (Spring 2015)
<br>&gt; <b>list assignments 3003023</b>
Found 9 assignments:
41508: Connected Components Warmup
41889: GiantBook
42653: Random Queue
43327: Congress
43574: Runsort
44343: Gorilla–Sea Cucumber Hash
44705: Word Ladders
44952: Spanning USA
45103: Super Vector Mario!
<br>&gt; <b>grade 44952</b>
Loading table...
Found 63 groups.
<br>grade&gt; <b>list</b>
No submission, No grade:
AG, AH, AP, BB, BE, BH, BL, BQ, Default group
Submitted for grading, Approved:
A, B, C, D, AA, AB
Submitted for grading, No grade:
E, F, G, H, I, J, K, L, M, N, O, P, Q, R, S, T, U, V, W, X, Y, Z, AC, AD, AE, AF, AI, AJ, AK, AL, AM, AN, AQ, AT, AU, AW, AX, AZ, BA, BC, BD, BF, BI, BJ, BM, BN, BO, BP
<br>grade&gt; <b>E</b>
Grade: -
Feedback:
Last modified: Thursday, 23 April 2015, 15:21
Submission status: Submitted for grading
Grading status: Unknown
Files: MST.java, SpanningUSA_final.pdf
Show files? [y/N]: <b>y</b> <i>files open, and feedback is written in vim</i>
[A]pproved/[N]ot approved/N[o] grade: <b>a</b>
Changes saved
<br>grade&gt; <b>E</b>
Grade: Approved
Feedback: Nice and short code, but Kruskal is not O(E+N)
...
