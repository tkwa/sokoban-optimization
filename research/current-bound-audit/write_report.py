from pathlib import Path
import json, datetime, hashlib
from bs4 import BeautifulSoup
root=Path(__file__).parent
project=root.parent.parent
candidates=json.loads((project/'research/candidates.json').read_text())
# MM, Rolling Stone, and PDB columns of Table 2, SoCS 2013, primary PDF p. 5.
pdb2013={13:[220,220,220],14:[231,231,231],15:[94,96,94],20:[302,446,358],22:[306,308,306],31:[228,232,232],32:[111,113,111],37:[220,242,220],41:[201,221,207],42:[208,208,208],50:[96,100,98],52:[365,367,369],56:[191,193,191],66:[185,187,185],69:[207,219,209],71:[290,294,290],74:[158,172,170]}
sokolution={}
s=BeautifulSoup((project/'research/source/xsokoban-optimal.html').read_text(),'html.parser')
for row in s.select('tr'):
    cells=[x.get_text(' ',strip=True) for x in row.find_all(['td','th'],recursive=False)]
    if len(cells)>=14 and cells[0].isdigit():
        n=int(cells[0])
        if 1<=n<=90: sokolution[n]={'row':cells,'solved':bool(cells[2]),'pushes':int(cells[2]) if cells[2].isdigit() else None}
assert len(sokolution)==90 and sum(x['solved'] for x in sokolution.values())==73
jsoko={}
s=BeautifulSoup((root/'jsoko-optimal.html').read_text(),'html.parser')
for row in s.select('tr'):
    cells=[x.get_text(' ',strip=True) for x in row.find_all(['td','th'],recursive=False)]
    if len(cells)>=14 and cells[0].isdigit():
        n=int(cells[0])
        if 1<=n<=90: jsoko[n]={'row':cells,'solved':bool(cells[2]),'pushes':int(cells[2]) if cells[2].isdigit() else None}
assert len(jsoko)==90 and sum(x['solved'] for x in jsoko.values())==25
rows=[]
for c in sorted(candidates['pool'],key=lambda c:c['number']):
    n=c['number']
    assert max(pdb2013[n])<=c['reported_lower']
    assert n in jsoko and not jsoko[n]['solved'],(n,jsoko.get(n))
    assert n in sokolution and not sokolution[n]['solved'],(n,sokolution.get(n))
    rows.append({
        'id':c['id'],'number':n,'selected':c['id'] in candidates['selected_ids'],
        'board_sha256':c['board_sha256'],
        'board_identity_basis':'Existing import audit matched current statistics layout to original Cornell XSokoban 3.3c archive, after canonicalization.',
        'strongest_public_numerical_lower_found':c['reported_lower'],
        'lower_source':'Pereira et al., IJCAI 2016, Table 1, maximum of initial-state columns 1I, 2I, 2D',
        'lower_source_url':'https://ijcai.org/proceedings/2016/0100.pdf',
        'lower_source_year':2016,
        'lower_is_final_search_frontier':False,
        'published_record_upper':c['reported_upper'],
        'record_url':c['record_url'],
        'documented_gap':c['reported_gap'],
        'current_statistics_static_lower_bound':int(sokolution[n]['row'][12]),
        'socs2013_lower_columns_mm_rs_pdb':pdb2013[n],
        'ijcai2016_proven_optimal_ub_highlighted':False,
        'sokolution_7_32_30_min_published_status':'not solved in push-optimal test',
        'jsoko_2_22_10_min_published_status':'not solved in push-optimal test',
        'later_optimality_claim_found':False,
        'known_optimum_status':'No optimum established for this board by sources inspected in this audit; this is not an exhaustive proof of absence.',
        'independent_certificate_status':'Separate release gate; source reports do not satisfy executable lower-certificate requirements.'
    })
report={
    'format':'sokogap-public-bound-audit-v1',
    'status':'Completed bounded public-source audit; certificate generation and upper-witness replay remain separate release gates.',
    'audit_local_date':'2026-10-26','audit_timezone':'America/Los_Angeles',
    'completed_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'conclusion':{
        'selected_count':10,
        'strongest_public_numerical_lower_source_found':'IJCAI 2016 initial-state heuristics',
        'selected_lower_total':sum(r['strongest_public_numerical_lower_found'] for r in rows if r['selected']),
        'selected_upper_total':sum(r['published_record_upper'] for r in rows if r['selected']),
        'selected_documented_gap':sum(r['documented_gap'] for r in rows if r['selected']),
        'newer_stronger_numeric_lower_records_found':0,
        'candidate_optimality_claims_found':0,
        'scope_language':'Strongest numerical lower bounds found in the inspected public sources as of 2026-10-26.',
        'scope_limitation':'There is no located comprehensive current lower-bound registry. Unpublished runs, inaccessible logs, and other unindexed work may give stronger bounds. Do not call these proven global lower-bound records.'
    },
    'instances':rows,
    'important_distinctions':[
        'The solver statistics Lower Bound column is a static heuristic field. It remains below solution cost on many solved boards, so it cannot be interpreted as the final search frontier or the strongest proved bound.',
        'A timeout in a push-optimal test indicates failure under that configuration and time limit. It does not itself prove optimality unresolved worldwide.',
        'IJCAI 2016 Table 1 highlights UB cells where search established an optimum. None of the 17 candidate UB cells is highlighted (checked visually). The paper mentions higher frontier f-values on timeout but does not tabulate the individual final f-values for unresolved boards.',
        'The SoCS article landing page currently gives a 2021 upload/publication date, but the paper is from SoCS 2013. It is not a newer numerical-bound source.',
        'Recent learned-solver results on Boxoban or arbitrary small boards do not establish bounds for these exact XSokoban layouts.',
        'Closed-source solver reports are research leads; benchmark lower bounds still require independently checked proof evidence.',
        'The current Sokolution homepage observed by the parent agent lists v7.32; the JSoko developer news page reports v7.33 on 2025-03-20, a crash fix for boards exceeding 1024 floors. Version-number discrepancy is preserved rather than resolved by assumption.'
    ],
    'sources_inspected':[
        {'id':'ijcai2016','url':'https://ijcai.org/proceedings/2016/0100.pdf','local_path':'../source/ijcai2016.pdf','findings':'Table 1 gives initial bounds used here. All 17 candidate optimum cells unhighlighted. Final frontier values mentioned but unlisted.'},
        {'id':'socs2013','url':'https://ojs.aaai.org/index.php/SOCS/article/download/18290/18081/21806','findings':'Table 2, PDF page 5: MM/RS/PDB bounds for all 17 checked. None exceeds the 2016 maximum. Full primary PDF read through web tool; local direct download failed.'},
        {'id':'sokolution-optimal','url':'https://sokoban-solver-statistics.sourceforge.io/statistics/Push-OptimalTestSuite/Sokolution%20-%20XSokoban.html','local_path':'../source/xsokoban-optimal.html','publication_date':'2025-04-11','findings':'73 of 90 solved in published push-optimal test; all 17 candidate boards not solved. Sokolution 7.32, 30 minutes, AMD Ryzen 9 7900X.'},
        {'id':'jsoko-optimal','url':'https://sokoban-solver-statistics.sourceforge.io/statistics/Push-OptimalTestSuite/JSoko%20-%20XSokoban.html','local_path':'jsoko-optimal.html','publication_date':'2025-02-08','findings':'JSoko 2.22, 10 minutes, 25 of 90 push-optimal solves. None of the 17 candidate boards solved.'},
        {'id':'live-comparison','url':'http://sokobano.de/wiki/index.php?title=Solver_Statistics','local_path':'sokobano-comparison.html','revision':8323,'findings':'Current comparison reports push-optimal solved totals: Rolling Stone 6, Pereira 28, JSoko 25, Sokolution 73. Sokolution source unavailable. Links to same optimal-statistics tables; no final-frontier records.'},
        {'id':'pereira-table','url':'http://sokobano.de/wiki/index.php?title=SolverStatistics-Pereira-ThinkingRabbit-XSokoban-Push-Optimal','local_path':'pareira-optimal.html','revision':5469,'findings':'Lists the 28 solved boards from IJCAI 2016; no candidate present.'},
        {'id':'sokolution-notes','url':'http://sokobano.de/wiki/index.php?title=Sokoban_solver_%22scribbles%22_by_Florent_Diedler_about_the_Sokolution_solver','local_path':'sokobano-sokolution.html','revision':6140,'findings':'Author technical description of matching/penalty pattern databases, optimal and nonoptimal modes. Historic description is older than 7.x; no current per-board lower record.'},
        {'id':'jsoko-news','url':'https://jsokoapplet.sourceforge.io/blog.php','findings':'Developer-maintained news read using web tool: Sokolution 7.33 released 2025-03-20 for a >1024-floor crash fix; newer JSoko versions through 2.29 in 2026. No new per-board XSokoban lower values. Direct fetch returned 404.'},
        {'id':'author-homepage','url':'https://www.inf.ufrgs.br/~agpereira/','local_path':'2016-author.html','findings':'Current selected publications through 2026 include IJCAI 2016 as latest dedicated XSokoban optimality paper; 2019 work concerns generation, later work broader planning. Public GitHub repositories also inspected; no released solver/results for the 2016 paper located.'},
        {'id':'author-repositories','url':'https://api.github.com/users/andregrahl/repos?per_page=100','local_path':'andregrahl-repos.json','findings':'Public repos andregrahl profile, CSrankings, leanplan. No per-board XSokoban result logs.'},
        {'id':'learning-deadlocks-2018','url':'https://lume.ufrgs.br/bitstream/handle/10183/190174/001088740.pdf','local_path':'2018-thesis.pdf','findings':'Jean Persi Boelter, Learning Deadlocks in Sokoban, December 2018. Experimental tables do not establish any of the candidate optima and do not give final-f numerical bounds for them.'},
        {'id':'ritt-publications','url':'https://ritt-home.net/doku.php?id=publications','findings':'Author bibliography through 2025; no newer exact-XSokoban numerical-bound paper located.'},
        {'id':'ritt-supplements','url':'https://ritt-home.net/doku.php?id=online_supplements','findings':'No Sokoban 2016 source code/results supplement linked.'},
        {'id':'solver-tools','url':'https://downloads.sourceforge.net/project/sokoban-solver-statistics/Sokoban_Solver_Statistics_Tools.zip','local_path':'../source/solver-tools.zip','findings':'Archive listing inspected. Contains nonoptimal 6.34 Sokolution result files and other solver traces; no 7.32 optimal timeout-frontier logs.'}
    ],
    'access_limits':[
        {'url':'https://lume.ufrgs.br/handle/10183/149574','reason':'Full 2016 dissertation landing page timed out; show=full returned a security-check page. No dissertation appendix was read.'},
        {'url':'https://www.sciencedirect.com/science/article/pii/S0004370215000867','reason':'2015journal full text unavailable; abstract inspected. 2016 paper supplies the 1I baseline from that work.'},
        {'url':'https://sokolution.infinityfreeapp.com/sokolutionv7.32-standalone.zip','reason':'Direct fetch returned JavaScript challenge HTML, not a ZIP. Parent agent has browser access and may obtain archive separately.'}
    ],
    'search_scope':{
        'search_terms':['XSokoban optimal lower bounds Sokolution 2026 2025','Sokoban optimal solver XSokoban lower bound 2024 2023','XSokoban Sokolution optimally solved 73 90','Sokolution 7.32 lower bound','XSokoban optimal solutions 73','Sokoban lower bounds Pereira 2017 2019 2025','Sokoban final frontier lower bound','Solving moving-blocks problems thesis Pereira'],
        'followed_primary_sources':'Current solver result tables, live comparison and author technical notes, release notes, 2016 paper and 2013 predecessor, 2018 thesis, 2016 author current webpage and public repositories, coauthor publication/supplement pages.',
        'not_done':['No people contacted or external messages sent.','No solver executable from an external source was run.','No claimed exhaustive proof that later bounds do not exist.']
    }
}
(root/'audit.json').write_text(json.dumps(report,indent=2)+'\n')
(root/'jsoko-candidate-rows.json').write_text(json.dumps({str(n):jsoko[n] for n in pdb2013},indent=2)+'\n')
(root/'sokolution-candidate-rows.json').write_text(json.dumps({str(n):sokolution[n] for n in pdb2013},indent=2)+'\n')
# Rename unsuccessful archive fetch so nobody mistakes it for executable software.
p=root/'sokolutionv7.32-standalone.zip'
if p.exists() and p.read_bytes().startswith(b'<html>'):
    p.rename(root/'sokolution-download-challenge.html')
    mp=root/'sokolutionv7.32-standalone.zip.meta.json'
    if mp.exists():mp.rename(root/'sokolution-download-challenge.html.meta.json')
print(json.dumps(report['conclusion'],indent=2))
