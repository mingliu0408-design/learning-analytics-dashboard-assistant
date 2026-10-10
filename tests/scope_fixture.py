from utils.c4_dashboard_scoped.scope import Scope, Snapshot, SourceSpec, Coverage, ScopeError
from utils.c4_dashboard_scoped.aggregate import aggregate
from dataclasses import replace
scope=Scope('learner','course','v1','2026-09-01T00:00:00+00:00','2026-09-08T00:00:00+00:00','UTC')
row={'ID':'learner','Course':'course','When':'2026-09-02T12:00:00+00:00','Event':'Resources_views','eid':'a'}
other={'ID':'other','Course':'other','When':'BAD_TIME_NOT_IN_SCOPE','Event':'Resources_views','eid':'foreign'}
spec=SourceSpec(columns=tuple(row),course_column='Course',observation='timestamp',time_column='When',event_id_column='eid',coverage=(Coverage(('learner',),'course',scope.start,scope.end,('resource_views',),'EXPLICIT_TEST_OBSERVATION_COVERAGE'),))
def result(rows,sp=spec):
 snap=Snapshot('v1',{'moodle':rows},{'moodle':sp},{'learner':('course',)},origin='SYNTHETIC')
 return aggregate(snap,scope).context(('Resources',))['activity']['Resources']['resource_views']
assert result((row,row,other))['value']==1
assert result(())['value']==0
assert result((),replace(spec,coverage=()))['value'] is None
assert result((dict(row,Course='other'),))['value']==0
assert result((dict(row,When='2026-09-08T00:00:00+00:00'),))['value']==0
assert result((row,dict(row,When='2026-09-03T00:00:00+00:00')))['value'] is None
try:
 aggregate(Snapshot('v1',{'moodle':(row,)},{'moodle':spec},{'learner':('different',)},origin='SYNTHETIC'),scope)
except ScopeError:pass
else:raise AssertionError('Course permission not enforced')
print('Scope filtering, deduplication, end-exclusive time, course and unknown/0 checks passed')
