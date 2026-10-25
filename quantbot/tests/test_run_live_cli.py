"""Recettes C2 sans terminal : le double reste exclusivement dans les tests."""
import ast
import importlib.util
import io
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace as NS

import pytest

from quantbot.live.state import StateStore
from tests.fake_mt5_live import FakeMT5Live

ROOT=Path(__file__).resolve().parents[1]
SCRIPT=ROOT/'scripts/run_live.py'
_spec=importlib.util.spec_from_file_location('run_live_cli',SCRIPT)
cli=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(cli)


def args(tmp, *extra):
    return ['--project',str(ROOT),'--state',str(tmp/'state.db'),'--kill-file',str(tmp/'KILL'),*extra]


def test_status_missing_is_read_only_and_does_not_import_mt5(tmp_path,monkeypatch,capsys):
    def forbidden(*a,**k):raise AssertionError('Chargement de MT5 interdit pour status')
    monkeypatch.setattr(cli.importlib,'import_module',forbidden)
    missing=tmp_path/'absent'
    assert cli.main(args(missing,'--status'))==0
    assert not missing.exists()
    assert json.loads(capsys.readouterr().out)['mode']=='NON_DEMARRE'


def test_status_existing_preserves_db_bytes_and_includes_unknown(tmp_path,capsys):
    s=StateStore(tmp_path/'state.db');s.set('mode','OBSERVATION');s.set('why','approbation absente')
    iid=s.new_intent('OPEN','long',{},'vwap');s.mark(iid,'UNKNOWN','timeout');s.close()
    before=(tmp_path/'state.db').read_bytes()
    assert cli.main(args(tmp_path,'--status'))==0
    result=json.loads(capsys.readouterr().out)
    assert result['unresolved_intents'][0]['status']=='UNKNOWN'
    assert result['kill_reasons'] and (tmp_path/'state.db').read_bytes()==before


def test_kill_only_creates_file_without_import_or_db(tmp_path,monkeypatch):
    monkeypatch.setattr(cli.importlib,'import_module',lambda *a:(_ for _ in ()).throw(AssertionError('MT5')))
    assert cli.main(args(tmp_path,'--kill'))==0
    assert (tmp_path/'KILL').is_file() and not (tmp_path/'state.db').exists()
    (tmp_path/'KILL').write_text('raison existante',encoding='utf-8')
    assert cli.main(args(tmp_path,'--kill'))==0
    assert (tmp_path/'KILL').read_text(encoding='utf-8')=='raison existante'


def test_clear_requires_human_interactive_input(tmp_path,monkeypatch):
    (tmp_path/'KILL').touch();monkeypatch.setattr(cli.sys,'stdin',io.StringIO('JE_COMPRENDS\n'))
    assert cli.main(args(tmp_path,'--clear-kill'))==1
    assert (tmp_path/'KILL').exists()


def test_clear_unknown_never_removes_flag_or_file(tmp_path):
    s=StateStore(tmp_path/'state.db');s.set('kill','ambigu');iid=s.new_intent('OPEN','long',{})
    s.mark(iid,'UNKNOWN');s.close();(tmp_path/'KILL').touch()
    assert cli.main(args(tmp_path,'--clear-kill'))==1
    assert (tmp_path/'KILL').exists()
    s=StateStore(tmp_path/'state.db');assert s.get('kill')=='ambigu';s.close()


def test_clear_explicit_confirmation_uses_existing_killswitch(tmp_path,monkeypatch):
    class TTY(io.StringIO):
        def isatty(self):return True
    s=StateStore(tmp_path/'state.db');s.set('kill','test uniquement');s.close();(tmp_path/'KILL').touch()
    monkeypatch.setattr(cli.sys,'stdin',TTY('JE_COMPRENDS\n'))
    assert cli.main(args(tmp_path,'--clear-kill'))==0
    assert not (tmp_path/'KILL').exists()
    s=StateStore(tmp_path/'state.db');assert not s.get('kill')
    assert any(e['kind']=='killswitch_clear' for e in s.recent_events());s.close()


def test_state_lock_rejects_second_launcher(tmp_path):
    with cli.state_lock(tmp_path/'state.db'):
        with pytest.raises(RuntimeError,match='autre lanceur'):
            with cli.state_lock(tmp_path/'state.db'):pass
    with cli.state_lock(tmp_path/'state.db'):pass


@pytest.mark.parametrize('poll',['nan','inf','0','-1'])
def test_invalid_poll_is_rejected_before_connection(tmp_path,poll):
    with pytest.raises(SystemExit):cli.arguments(args(tmp_path,'--poll',poll))


def test_path_collision_rejected(tmp_path):
    with pytest.raises(SystemExit):cli.arguments(['--state',str(tmp_path/'same'),'--kill-file',str(tmp_path/'same')])


def install_test_terminal(monkeypatch,terminal):
    def initialize(*a,**kw):terminal.initialized=True;return True
    terminal.initialize=initialize
    terminal.terminal_info=lambda:NS(connected=True)
    original=cli.importlib.import_module
    monkeypatch.setattr(cli.importlib,'import_module',lambda n,*a,**kw:terminal if n=='MetaTrader5' else original(n,*a,**kw))


def test_unapproved_observation_actual_runner_no_order_apis(tmp_path,monkeypatch,capsys):
    terminal=FakeMT5Live(n_bars=1500)
    install_test_terminal(monkeypatch,terminal)
    assert cli.main(args(tmp_path,'--max-steps','2','--poll','.1'))==0
    assert terminal.sent==[] and terminal.checked==[] and not terminal.initialized
    s=StateStore(tmp_path/'state.db');assert s.get('mode')=='OBSERVATION'
    assert s.get('launcher_running') is False and not s.open_intents();s.close()
    assert 'PAPER sur prix MT5 réels' in capsys.readouterr().out
    assert not (ROOT/'approved_strategies.json').exists()


def test_real_account_refused_before_runner(tmp_path,monkeypatch):
    terminal=FakeMT5Live(demo=False);install_test_terminal(monkeypatch,terminal)
    assert cli.main(args(tmp_path,'--max-steps','1'))==1
    assert not (tmp_path/'state.db').exists() and terminal.sent==[]


def test_wrong_server_refused_before_runner(tmp_path,monkeypatch):
    terminal=FakeMT5Live(server='AUTRE');install_test_terminal(monkeypatch,terminal)
    assert cli.main(args(tmp_path,'--max-steps','1'))==1
    assert not (tmp_path/'state.db').exists() and terminal.sent==[]


def test_pending_intent_refuses_replay_before_initialize(tmp_path,monkeypatch):
    s=StateStore(tmp_path/'state.db');s.new_intent('OPEN','long',{});s.close()
    terminal=FakeMT5Live();terminal.initialize=lambda *a,**k:(_ for _ in ()).throw(AssertionError('connexion'))
    original=cli.importlib.import_module
    monkeypatch.setattr(cli.importlib,'import_module',lambda n,*a,**k:terminal if n=='MetaTrader5' else original(n,*a,**k))
    assert cli.main(args(tmp_path,'--max-steps','1'))==1
    assert terminal.sent==[]


def test_ctrl_c_persists_stop_and_closes_resources(tmp_path,monkeypatch):
    terminal=FakeMT5Live(n_bars=1500);install_test_terminal(monkeypatch,terminal)
    monkeypatch.setattr(cli.time,'sleep',lambda _:(_ for _ in ()).throw(KeyboardInterrupt()))
    assert cli.main(args(tmp_path))==130
    s=StateStore(tmp_path/'state.db');assert s.get('launcher_running') is False
    assert 'Ctrl+C' in s.get('launcher_stop_reason');s.close()
    assert not terminal.initialized and not terminal.sent


def test_no_send_check_or_fake_import_in_launcher():
    tree=ast.parse(SCRIPT.read_text(encoding='utf-8'))
    assert not any(isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr in ('order_send','order_check') for n in ast.walk(tree))
    imports=[n.module or '' for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)]
    assert not any(n.startswith('tests') for n in imports)


def test_account_change_is_refused_and_logs_mask_login():
    terminal=FakeMT5Live();terminal.terminal_info=lambda:NS(connected=True)
    identity=cli.account_guard(terminal,('MetaQuotes-Demo',))
    terminal.acct.login=99887766
    with pytest.raises(PermissionError):cli.account_guard(terminal,('MetaQuotes-Demo',),identity)
    assert '99887766' not in cli.safe_text('erreur compte 99887766',99887766)


# --- erreurs de cycle : transitoires = pas de drapeau persistant (revue Claude) --------------------------------------
def _terminal_with_dead_feed_after_setup(monkeypatch):
    terminal=FakeMT5Live(n_bars=1500);install_test_terminal(monkeypatch,terminal)
    real=terminal.copy_rates_from_pos
    calls={'n':0}
    def rates(*a,**k):
        calls['n']+=1
        return real(*a,**k) if calls['n']<=1 else None   # 1er appel = historique de démarrage ; ensuite : lecture impossible
    terminal.copy_rates_from_pos=rates
    return terminal


def test_few_transient_cycle_errors_do_not_set_persistent_kill(tmp_path,monkeypatch):
    _terminal_with_dead_feed_after_setup(monkeypatch)
    monkeypatch.setattr(cli.time,'sleep',lambda _:None)
    assert cli.main(args(tmp_path,'--max-steps','3'))==0
    s=StateStore(tmp_path/'state.db');assert not s.get('kill');s.close()
    assert not (tmp_path/'KILL').exists()


def test_too_many_consecutive_errors_stop_cleanly_without_persistent_kill(tmp_path,monkeypatch,capsys):
    _terminal_with_dead_feed_after_setup(monkeypatch)
    monkeypatch.setattr(cli.time,'sleep',lambda _:None)
    assert cli.main(args(tmp_path,'--max-steps','50'))==1
    s=StateStore(tmp_path/'state.db');assert not s.get('kill');assert s.get('launcher_running') is False
    assert 'consécutives' in s.get('launcher_stop_reason');s.close()
    assert capsys.readouterr().out.count('ERREUR_CYCLE')==cli.MAX_CONSECUTIVE_ERRORS


def test_unexpected_crash_sets_persistent_kill(tmp_path,monkeypatch):
    terminal=FakeMT5Live(n_bars=1500);install_test_terminal(monkeypatch,terminal)
    monkeypatch.setattr(cli.time,'sleep',lambda _:None)
    from quantbot.live.runner import LiveRunner
    orig=LiveRunner.setup
    def setup(self):
        mode=orig(self);self.engine.on_bar=lambda df:(_ for _ in ()).throw(RuntimeError('bug'));return mode
    monkeypatch.setattr(LiveRunner,'setup',setup)
    terminal_advance=terminal.advance
    # une barre neuve arrive après l'amorçage : le moteur plante
    n={'k':0}
    orig_step=LiveRunner.step
    def step(self):
        n['k']+=1
        if n['k']==2:terminal_advance(1)
        return orig_step(self)
    monkeypatch.setattr(LiveRunner,'step',step)
    assert cli.main(args(tmp_path,'--max-steps','4'))==1
    s=StateStore(tmp_path/'state.db');assert s.get('kill');s.close()


# --- résolution humaine d'une intention non rapprochée (prérequis C5) ---------------------------------------------------
class _TTY(io.StringIO):
    def isatty(self):return True


def _unknown(tmp):
    s=StateStore(tmp/'state.db');iid=s.new_intent('OPEN','long',{},'vwap');s.mark(iid,'UNKNOWN','timeout');s.set('kill','ambigu');s.close()
    return iid


def test_resolve_requires_outcome_and_ticket_when_executed(tmp_path):
    with pytest.raises(SystemExit):cli.arguments(args(tmp_path,'--resolve-intent','x'))
    with pytest.raises(SystemExit):cli.arguments(args(tmp_path,'--resolve-intent','x','--outcome','EXECUTED'))
    with pytest.raises(SystemExit):cli.arguments(args(tmp_path,'--resolve-intent','x','--outcome','NOT_EXECUTED','--ticket','5'))


def test_resolve_needs_interactive_exact_confirmation(tmp_path,monkeypatch):
    iid=_unknown(tmp_path)
    monkeypatch.setattr(cli.sys,'stdin',io.StringIO('JE_VERIFIE_LE_TERMINAL\n'))      # pas un TTY
    assert cli.main(args(tmp_path,'--resolve-intent',iid,'--outcome','NOT_EXECUTED'))==1
    monkeypatch.setattr(cli.sys,'stdin',_TTY('oui\n'))
    assert cli.main(args(tmp_path,'--resolve-intent',iid,'--outcome','NOT_EXECUTED'))==1
    s=StateStore(tmp_path/'state.db');assert s.intent(iid)['status']=='UNKNOWN';s.close()


def test_resolve_not_executed_closes_intent_but_keeps_kill_flag(tmp_path,monkeypatch):
    iid=_unknown(tmp_path);(tmp_path/'KILL').touch()
    monkeypatch.setattr(cli.sys,'stdin',_TTY('JE_VERIFIE_LE_TERMINAL\n'))
    assert cli.main(args(tmp_path,'--resolve-intent',iid,'--outcome','NOT_EXECUTED'))==0
    s=StateStore(tmp_path/'state.db')
    assert s.intent(iid)['status']=='RESOLVED_NOT_EXECUTED' and not s.open_intents()
    assert s.get('kill')=='ambigu' and (tmp_path/'KILL').exists()                    # levée du coupe-circuit = autre action humaine
    s.close()


def test_resolve_executed_records_ticket_and_refuses_double_resolution(tmp_path,monkeypatch):
    iid=_unknown(tmp_path)
    monkeypatch.setattr(cli.sys,'stdin',_TTY('JE_VERIFIE_LE_TERMINAL\n'))
    assert cli.main(args(tmp_path,'--resolve-intent',iid,'--outcome','EXECUTED','--ticket','4242'))==0
    s=StateStore(tmp_path/'state.db');assert 4242 in s.known_tickets();s.close()
    monkeypatch.setattr(cli.sys,'stdin',_TTY('JE_VERIFIE_LE_TERMINAL\n'))
    assert cli.main(args(tmp_path,'--resolve-intent',iid,'--outcome','NOT_EXECUTED'))==1


def test_resolve_unknown_id_or_missing_db_fails(tmp_path,monkeypatch):
    monkeypatch.setattr(cli.sys,'stdin',_TTY('JE_VERIFIE_LE_TERMINAL\n'))
    assert cli.main(args(tmp_path,'--resolve-intent','nope','--outcome','NOT_EXECUTED'))==1
    _unknown(tmp_path)
    assert cli.main(args(tmp_path,'--resolve-intent','nope','--outcome','NOT_EXECUTED'))==1
