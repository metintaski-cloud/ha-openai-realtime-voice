"""She must never stand still as a picture because a mood has no clip, and never answer Metin in English."""
import json
import re
import shutil
import subprocess

import pytest

from app import chat, memory_web


def test_a_hurt_leyla_in_a_work_dress_plays_the_happy_loop_instead_of_standing_still(tmp_path):
    """25 Nov 2026: she was hurt, the work dresses have no sad clips any more, and the stage showed only her picture."""
    node = shutil.which("node")
    if not node:
        pytest.skip("no node here")
    app = open(memory_web.__file__, encoding="utf-8").read()
    picks = re.search(r"function clipVars\(b\)\{.*?\n(?=/\* light copies)", app, re.S).group(0)
    assert "function clipFor(st){" in picks
    path = tmp_path / "pick.js"
    path.write_text("""
let STM=null,CLIPS=[],NIGHT=[];const CHANGE=['umziehen'];
""" + picks + """
const work=['begruessung','brust','gesicht','gluecklich4','gluecklich5','gluecklich6','gluecklichextra','po','umziehen'];
const out={};
const run=(key,clips,night,st)=>{CLIPS=clips;NIGHT=night;STM=st;out[key]=clipFor(st);};
run('hurt_work',work,[],{low:true,level:'leicht',mood:'traurig',outfit:'arbeit'});
run('hurt_hard_work',work,[],{low:true,level:'schwer',mood:'sauer',outfit:'arbeit'});
run('jealous_work',work,[],{low:true,level:'leicht',mood:'eifersuechtig',outfit:'arbeit'});
run('good_work',work,[],{low:false,mood:'verliebt',outfit:'arbeit'});
run('hurt_work_with_sad',work.concat(['traurigleicht','traurigleicht2']),[],{low:true,level:'leicht',mood:'traurig',outfit:'arbeit'});
run('hurt_leisure',['freizeitgluecklich','freizeitgluecklich2'],[],{low:true,level:'leicht',mood:'traurig',outfit:'freizeit'});
run('hurt_leisure_jealous',['freizeitgluecklich','freizeiteifersuechtig'],[],{low:true,level:'mittel',mood:'traurig',outfit:'freizeit'});
run('hurt_night',[],['gluecklich','gluecklich2'],{low:true,level:'leicht',mood:'einsam',outfit:'nacht'});
run('nothing',['begruessung'],[],{low:true,level:'leicht',mood:'traurig',outfit:'arbeit'});
console.log(JSON.stringify(out));
""", encoding="utf-8")
    done = subprocess.run([node, str(path)], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout) == {
        "hurt_work": "gluecklich", "hurt_hard_work": "gluecklich", "jealous_work": "gluecklich",
        "good_work": "gluecklich", "hurt_work_with_sad": "traurigleicht",   # a sad clip still wins when there is one
        "hurt_leisure": "gluecklich", "hurt_leisure_jealous": "eifersuechtig", "hurt_night": "gluecklich",
        "nothing": None}


def test_she_never_answers_metin_in_english():
    """He cannot read English; on 25 Nov 2026 the speech recogniser wrote "Hello." and she answered in English."""
    for rules in (chat.CHAT_STYLE, chat.CHAT_KOPF):
        assert "versteht kein Englisch. Antworte ihm nie auf Englisch." in rules
        assert "antworte auf Deutsch" in rules
