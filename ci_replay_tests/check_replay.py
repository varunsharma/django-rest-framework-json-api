"""Isolated contract tests: no Redis service is required."""
import json
import os
from pathlib import Path
import subprocess
import sys

PLUGIN = Path(__file__).resolve().parents[1]


def run_suite(tmp_path, source, **extra_env):
    (tmp_path / 'test_sample.py').write_text(source)
    for bytecode in tmp_path.rglob('*.pyc'):
        bytecode.unlink()
    env = dict(os.environ, PYTHONPATH=str(PLUGIN), CI_REPLAY_BRANCH='feature/replay',
               CI_REPLAY_LANE='unit', CI_REPLAY_CACHE_DIR=str(tmp_path / 'history'))
    env.update(extra_env)
    return subprocess.run([sys.executable, '-m', 'pytest', '-p', 'ci_replay',
                           '--confcutdir=' + str(tmp_path), '-q'], cwd=str(tmp_path),
                          env=env, text=True, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT)


def history(tmp_path):
    return json.loads(next((tmp_path / 'history').glob('*.json')).read_text())


def test_first_failure_stops_and_checkpoint_survives(tmp_path):
    result = run_suite(tmp_path, 'def test_a(): assert False\ndef test_b(): assert False\n')
    assert result.returncode == 1, result.stdout
    state = history(tmp_path)
    assert state['failed'] == ['test_sample.py::test_a']
    assert state['pending'] == ['test_sample.py::test_b']
    assert state['contexts'][-1]['branch'] == 'feature/replay'


def test_known_failure_precedes_interrupted_and_full_suite(tmp_path):
    source = 'def test_a(): pass\ndef test_b(): assert False\ndef test_c(): assert False\n'
    assert run_suite(tmp_path, source).returncode == 1
    result = run_suite(tmp_path, source.replace('def test_a(): pass', 'def test_a(): assert False'))
    assert result.returncode == 1, result.stdout
    assert 'test_sample.py::test_b' in result.stdout
    assert history(tmp_path)['failed'] == ['test_sample.py::test_b']


def test_fixed_failure_and_interrupted_tests_then_full_suite(tmp_path):
    assert run_suite(tmp_path, 'def test_a(): assert False\ndef test_b(): pass\n').returncode == 1
    result = run_suite(tmp_path, 'def test_a(): pass\ndef test_b(): pass\n')
    assert result.returncode == 0, result.stdout
    state = history(tmp_path)
    assert state['failed'] == [] and state['pending'] == []
    assert state['risk']['test_sample.py::test_a'] == 1


def test_branch_history_is_isolated(tmp_path):
    assert run_suite(tmp_path, 'def test_a(): assert False\n').returncode == 1
    result = run_suite(tmp_path, 'def test_a(): pass\n', CI_REPLAY_BRANCH='other')
    assert result.returncode == 0, result.stdout
    assert len(list((tmp_path / 'history').glob('*.json'))) == 2


def test_repository_history_is_isolated(tmp_path):
    assert run_suite(tmp_path, 'def test_a(): assert False\n', TRAVIS_REPO_SLUG='org/first').returncode == 1
    result = run_suite(tmp_path, 'def test_a(): pass\n', TRAVIS_REPO_SLUG='org/second')
    assert result.returncode == 0, result.stdout
    assert len(list((tmp_path / 'history').glob('*.json'))) == 2


def test_corrupt_history_blocks_test_execution(tmp_path):
    assert run_suite(tmp_path, 'def test_a(): pass\n').returncode == 0
    next((tmp_path / 'history').glob('*.json')).write_text('{broken')
    result = run_suite(tmp_path, 'def test_a(): assert False\n')
    assert result.returncode != 0
    assert 'Invalid replay history' in result.stdout
    assert 'FAILED test_sample.py' not in result.stdout


def test_interrupted_test_precedes_new_failure_after_known_test_is_fixed(tmp_path):
    source = 'def test_a(): pass\ndef test_b(): assert False\ndef test_c(): assert False\n'
    assert run_suite(tmp_path, source).returncode == 1
    source = source.replace('def test_a(): pass', 'def test_a(): assert False')
    source = source.replace('def test_b(): assert False', 'def test_b(): pass')
    result = run_suite(tmp_path, source)
    assert result.returncode == 1, result.stdout
    assert 'FAILED test_sample.py::test_c' in result.stdout
    assert history(tmp_path)['failed'] == ['test_sample.py::test_c']


def test_collection_errors_are_checkpointed_without_running_tests(tmp_path):
    result = run_suite(tmp_path, 'raise RuntimeError("collection error")\n')
    assert result.returncode != 0
    assert history(tmp_path)['failed'] == ['test_sample.py']
    result = run_suite(tmp_path, 'def test_a(): pass\n')
    assert result.returncode == 0, result.stdout
    assert history(tmp_path)['failed'] == []


def test_checkpoint_write_error_blocks_test_execution(tmp_path):
    marker = tmp_path / 'executed'
    cache = tmp_path / 'history'
    cache.write_text('not a directory')
    source = 'def test_a():\n    open(%r, "w").close()\n' % str(marker)
    result = run_suite(tmp_path, source)
    assert result.returncode != 0
    assert not marker.exists()


def test_successful_replay_retains_previous_run_context(tmp_path):
    assert run_suite(tmp_path, 'def test_a(): assert False\n', TRAVIS_PULL_REQUEST='123', TRAVIS_BUILD_ID='456').returncode == 1
    result = run_suite(tmp_path, 'def test_a(): pass\n', TRAVIS_PULL_REQUEST='124', TRAVIS_BUILD_ID='457')
    assert result.returncode == 0, result.stdout
    assert [c['pr'] for c in history(tmp_path)['contexts']] == ['123', '124']
    assert [c['run'] for c in history(tmp_path)['contexts']] == ['456', '457']


def test_skipping_previous_failure_does_not_mark_it_fixed(tmp_path):
    assert run_suite(tmp_path, 'def test_a(): assert False\n').returncode == 1
    result = run_suite(tmp_path, 'import pytest\n@pytest.mark.skip\ndef test_a(): pass\n')
    assert result.returncode == 0, result.stdout
    assert history(tmp_path)['failed'] == ['test_sample.py::test_a']


def test_first_collection_error_stops_before_later_module(tmp_path):
    (tmp_path / 'test_z.py').write_text('raise RuntimeError("later collection error")\n')
    result = run_suite(tmp_path, 'raise RuntimeError("first collection error")\n')
    assert result.returncode != 0
    assert history(tmp_path)['failed'] == ['test_sample.py']
    assert 'later collection error' not in result.stdout
