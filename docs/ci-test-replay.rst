CI test replay
==============

The Travis tox test environments load ``ci_replay.py`` with
``-p ci_replay --maxfail=1``. Previously failed tests run first, followed by
tests left pending by an interrupted run, changed-source risk cases, and the
rest of the suite. A failure stops the current pytest invocation immediately.
The existing pytest test discovery and database settings remain in place.

History is scoped to the repository, branch, tox environment, and Python
runtime. It stores test IDs, bounded risk counts, and the last twelve run
contexts with repository, branch, pull request, commit, run, job, lane, and
Python version. It does not store assertions, exception bodies, logs, or
environment dumps. Checkpoints are written atomically before test execution
and after each collection or test result.

This repository does not configure a persistent Travis cache for
``.ci-replay-cache``. Jobs may therefore start cold and use ordinary pytest
discovery order. History is best-effort prioritization and is not needed for a
correct test run. Invalid or unsupported history fails the test invocation
before tests continue.

The Travis configuration runs its Python/Django/DRF matrix as separate jobs.
A failure stops tests in the current job, while sibling jobs that are already
running may continue. This change does not cancel by branch, commit, or pull
request.

The application matrix includes Python 2.7 and Python 3.2 through 3.5 with
pytest 2.8.2. The isolated adapter contract checks use modern Python and pytest
and are kept out of the application's default test collection.
