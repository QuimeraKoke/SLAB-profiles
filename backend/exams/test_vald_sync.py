"""Tests for the VALD Hub → ExamResult sync (mapping, matching, dedup).

The VALD client is mocked (`FakeValdClient`); these tests exercise the sync
service against real seeded strength templates so the field_key mappings and
`compute_result_data` calculated fields are validated end-to-end.
"""

from unittest import mock

from django.core.management import call_command
from django.test import TestCase

from core.models import Category, Club, Department, Player
from exams.models import ExamResult, ValdIntegration, ValdProfileLink
from integrations.vald_hub import ValdProfile

PID_NAME = "vald-charles"
PID_EXT = "vald-ext"
PID_AMB = "vald-amb"


class FakeValdClient:
    """Stand-in for ValdHubClient. Tests set the class-level canned data."""

    PROFILES: list[dict] = []
    FD: list[dict] = []           # modern /tests list (metadata only)
    TRIALS: dict = {}             # testId -> [ {resultName: scaled_value}, ... ]
    FF: list[dict] = []
    NB: list[dict] = []
    DEFS: dict = {}

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def list_profiles(self, modified_from=None):
        return [ValdProfile.from_api(p) for p in self.PROFILES]

    def get_forcedecks_result_definitions(self):
        return self.DEFS

    def list_forcedecks_tests(self, modified_from=None):
        return list(self.FD)

    def forcedecks_test_trials_metrics(self, test_id):
        return list(self.TRIALS.get(test_id, []))

    def list_forceframe_tests(self, modified_from=None):
        return list(self.FF)

    def list_nordbord_tests(self, modified_from=None):
        return list(self.NB)


FD_DEFS = {
    1: {"name": "Jump Height (Imp-Mom)", "scale": 1.0, "unit": "cm"},
    2: {"name": "Peak Power / BM", "scale": 1.0, "unit": "W/kg"},
    3: {"name": "RSI-modified", "scale": 1.0, "unit": "m/s"},
    4: {"name": "Eccentric Peak Velocity", "scale": 1.0, "unit": "m/s"},
    10: {"name": "Peak Vertical Force", "scale": 1.0, "unit": "N"},
    11: {"name": "Peak Vertical Force / BM", "scale": 1.0, "unit": "N/kg"},
    12: {"name": "RFD - 200ms", "scale": 1.0, "unit": "N/s"},
    99: {"name": "Some Unmapped Metric", "scale": 1.0, "unit": "x"},
}


class ValdSyncTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.club = Club.objects.create(name="Test FC")
        cls.dept = Department.objects.create(club=cls.club, name="Médico", slug="medico")
        cls.cat = Category.objects.create(club=cls.club, name="Primer Equipo")
        # Real strength templates (cmj/imtp/hip_adab/nordico) + alert rules.
        call_command(
            "seed_medico_indicators", club=cls.club.name,
            only="cmj,imtp,hip_adab,nordico", create_if_missing=True,
        )
        cls.charles = Player.objects.create(
            first_name="Charles", last_name="Aránguiz", category=cls.cat, is_active=True,
        )
        cls.ext_player = Player.objects.create(
            first_name="Externo", last_name="Vinculado", category=cls.cat, is_active=True,
        )
        # Two identically-named players → ambiguous (no DOB) → unresolved.
        Player.objects.create(first_name="Juan", last_name="Pérez", category=cls.cat, is_active=True)
        Player.objects.create(first_name="Juan", last_name="Pérez", category=cls.cat, is_active=True)
        cls.integ = ValdIntegration.objects.create(
            club=cls.club, enabled=True, region="use", tenant_id="tenant-guid",
            client_id="cid", client_secret="secret",
        )

    def _profiles(self):
        return [
            {"profileId": PID_NAME, "givenName": "Charles", "familyName": "Aranguiz",
             "modifiedDateUtc": "2026-05-01T00:00:00Z"},
            {"profileId": PID_EXT, "givenName": "Zzz", "familyName": "Zzz",
             "externalId": str(self.ext_player.id), "modifiedDateUtc": "2026-05-01T00:00:00Z"},
            {"profileId": PID_AMB, "givenName": "Juan", "familyName": "Perez",
             "modifiedDateUtc": "2026-05-01T00:00:00Z"},
        ]

    def _configure(self, **over):
        FakeValdClient.PROFILES = over.get("profiles", self._profiles())
        FakeValdClient.DEFS = over.get("defs", FD_DEFS)
        FakeValdClient.FD = over.get("fd", [])
        FakeValdClient.TRIALS = over.get("trials", {})
        FakeValdClient.FF = over.get("ff", [])
        FakeValdClient.NB = over.get("nb", [])

    def _run(self, **kwargs):
        from exams.services import vald_sync
        with mock.patch.object(vald_sync, "ValdHubClient", FakeValdClient):
            return vald_sync.sync_club(self.club, **kwargs)

    # -- matching -----------------------------------------------------------

    def test_profile_matching(self):
        self._configure()
        report = self._run()
        self.assertEqual(report["status"], "ok")
        by_pid = {l.vald_profile_id: l for l in ValdProfileLink.objects.filter(club=self.club)}
        self.assertEqual(by_pid[PID_NAME].player_id, self.charles.id)
        self.assertEqual(by_pid[PID_NAME].match_method, ValdProfileLink.MATCH_NAME)
        self.assertEqual(by_pid[PID_EXT].player_id, self.ext_player.id)
        self.assertEqual(by_pid[PID_EXT].match_method, ValdProfileLink.MATCH_EXTERNAL_ID)
        self.assertIsNone(by_pid[PID_AMB].player_id)
        self.assertEqual(by_pid[PID_AMB].match_method, ValdProfileLink.MATCH_UNRESOLVED)
        self.assertEqual(report["profiles_unresolved"], 1)

    def test_manual_link_not_overwritten(self):
        self._configure()
        self._run()
        link = ValdProfileLink.objects.get(club=self.club, vald_profile_id=PID_AMB)
        link.player = self.charles
        link.match_method = ValdProfileLink.MATCH_MANUAL
        link.save()
        self._run()  # re-sync
        link.refresh_from_db()
        self.assertEqual(link.player_id, self.charles.id)
        self.assertEqual(link.match_method, ValdProfileLink.MATCH_MANUAL)

    # -- ForceDecks ---------------------------------------------------------

    def test_forcedecks_cmj_imtp_mapping(self):
        # Metrics come from the (already scale-applied) legacy trials endpoint,
        # keyed by testId — the modern list is metadata only.
        self._configure(
            fd=[
                {"testId": "t-cmj", "profileId": PID_NAME, "testType": "CMJ",
                 "recordedDateUtc": "2026-05-02T10:00:00Z", "modifiedDateUtc": "2026-05-02T10:00:00Z"},
                {"testId": "t-imtp", "profileId": PID_NAME, "testType": "IMTP",
                 "recordedDateUtc": "2026-05-03T10:00:00Z", "modifiedDateUtc": "2026-05-03T10:00:00Z"},
            ],
            trials={
                "t-cmj": [{
                    "Jump Height (Imp-Mom)": 42.5, "Peak Power / BM": 55.0,
                    "RSI-modified": 0.45, "Eccentric Peak Velocity": 2.9,
                    "Some Unmapped Metric": 123.0,
                }],
                "t-imtp": [{
                    "Peak Vertical Force": 3200.0, "Peak Vertical Force / BM": 38.0,
                    "RFD - 200ms": 8500.0,
                }],
            },
        )
        report = self._run()
        self.assertEqual(report["created"], 2)
        cmj = ExamResult.objects.get(player=self.charles, template__slug="cmj")
        self.assertEqual(cmj.result_data["jump_height"], 42.5)
        self.assertEqual(cmj.result_data["peak_power_bodymass"], 55.0)
        self.assertEqual(cmj.result_data["rsi_modified"], 0.45)
        self.assertEqual(cmj.result_data["ecc_peak_velocity"], 2.9)
        self.assertNotIn("Some Unmapped Metric", cmj.result_data)  # unmapped dropped
        imtp = ExamResult.objects.get(player=self.charles, template__slug="imtp")
        self.assertEqual(imtp.result_data["peak_vertical_force"], 3200.0)
        self.assertEqual(imtp.result_data["rfd_200ms"], 8500.0)

    def test_forcedecks_per_rep_max_within_one_test(self):
        # ONE recording with 3 reps → per-metric max across reps, so fields can
        # come from different reps (the real BIANNEIDER TAMAYO case: the ecc peak
        # sits in a different rep than the jump peak).
        self._configure(
            fd=[{"testId": "t-multi", "profileId": PID_NAME, "testType": "CMJ",
                 "recordedDateUtc": "2026-05-02T14:00:00Z", "modifiedDateUtc": "2026-05-02T14:00:00Z"}],
            trials={"t-multi": [
                {"Jump Height (Imp-Mom)": 38.5, "Eccentric Peak Velocity": -1.76, "Peak Power / BM": 53.0},
                {"Jump Height (Imp-Mom)": 39.2, "Eccentric Peak Velocity": -1.72, "Peak Power / BM": 52.2},
                {"Jump Height (Imp-Mom)": 38.4, "Eccentric Peak Velocity": -1.11, "Peak Power / BM": 52.3},
            ]},
        )
        self.assertEqual(self._run()["created"], 1)
        cmj = ExamResult.objects.get(player=self.charles, template__slug="cmj")
        self.assertEqual(cmj.result_data["jump_height"], 39.2)          # rep 1
        self.assertEqual(cmj.result_data["ecc_peak_velocity"], -1.11)   # rep 2 (max = least negative)
        self.assertEqual(cmj.result_data["peak_power_bodymass"], 53.0)  # rep 0

    def test_forcedecks_best_test_across_same_day_sessions(self):
        # TWO separate recordings same day → keep the single best test by the
        # primary metric, NOT a per-metric merge across sessions (real MATIAS
        # ZALDIVIA IMTP case: test B wins on peak force, so its rfd is kept).
        self._configure(
            fd=[
                {"testId": "t-A", "profileId": PID_NAME, "testType": "IMTP",
                 "recordedDateUtc": "2026-05-03T09:00:00Z", "modifiedDateUtc": "2026-05-03T09:00:00Z"},
                {"testId": "t-B", "profileId": PID_NAME, "testType": "IMTP",
                 "recordedDateUtc": "2026-05-03T10:00:00Z", "modifiedDateUtc": "2026-05-03T10:00:00Z"},
            ],
            trials={
                "t-A": [{"Peak Vertical Force": 2274.0, "RFD - 200ms": 1503.0}],
                "t-B": [{"Peak Vertical Force": 2388.0, "RFD - 200ms": 1050.0}],
            },
        )
        self.assertEqual(self._run()["created"], 1)
        imtp = ExamResult.objects.get(player=self.charles, template__slug="imtp")
        self.assertEqual(imtp.result_data["peak_vertical_force"], 2388.0)  # best test = B
        self.assertEqual(imtp.result_data["rfd_200ms"], 1050.0)            # B's rfd, not A's 1503

    def test_client_applies_scale_factor(self):
        # The client resolves resultId→name and multiplies by scaleFactor
        # (e.g. RSI-modified is stored ×0.01 in VALD's SI base).
        from integrations.vald_hub import ValdHubClient
        c = ValdHubClient(region="use", tenant_id="t", client_id="x", client_secret="y")
        c._result_definitions = {5: {"name": "RSI-modified", "scale": 0.01, "unit": "m/s"}}
        with mock.patch.object(
            c, "_get",
            return_value=[{"results": [{"resultId": 5, "value": 22.0, "limb": "Trial"},
                                       {"resultId": 5, "value": 99.0, "limb": "Left"}]}],
        ):
            metrics = c.forcedecks_test_trials_metrics("t1")
        self.assertEqual(metrics, [{"RSI-modified": 0.22}])  # scaled; Left ignored

    # -- ForceFrame ---------------------------------------------------------

    def test_forceframe_hip_channels(self):
        self._configure(ff=[
            {"testId": "t-ff", "profileId": PID_NAME,
             "testTypeName": "Hip Adduction/Abduction", "testPositionName": "Hip",
             "testDateUtc": "2026-05-04T09:00:00Z", "modifiedDateUtc": "2026-05-04T09:00:00Z",
             "innerLeftMaxForce": 300.0, "innerRightMaxForce": 330.0,
             "outerLeftMaxForce": 250.0, "outerRightMaxForce": 255.0},
            # A non-hip ForceFrame test must be ignored.
            {"testId": "t-knee", "profileId": PID_NAME, "testTypeName": "Knee Flexion",
             "testDateUtc": "2026-05-05T09:00:00Z", "modifiedDateUtc": "2026-05-05T09:00:00Z",
             "innerLeftMaxForce": 1.0, "innerRightMaxForce": 1.0},
        ])
        report = self._run()
        self.assertEqual(report["created"], 1)
        r = ExamResult.objects.get(player=self.charles, template__slug="hip_adab")
        self.assertEqual(r.result_data["squeeze_left_max"], 300.0)   # inner
        self.assertEqual(r.result_data["squeeze_right_max"], 330.0)
        self.assertEqual(r.result_data["pull_left_max"], 250.0)      # outer
        self.assertEqual(r.result_data["pull_right_max"], 255.0)
        # calculated imbalance present (right-minus-left over left, %)
        self.assertIn("squeeze_imbalance", r.result_data)
        self.assertAlmostEqual(r.result_data["squeeze_imbalance"], 10.0, places=1)

    # -- NordBord -----------------------------------------------------------

    def test_nordbord_mapping_and_unmatched(self):
        self._configure(nb=[
            {"testId": "t-nb", "profileId": PID_NAME, "testTypeName": "Nordic",
             "testDateUtc": "2026-05-06T09:00:00Z", "modifiedDateUtc": "2026-05-06T09:00:00Z",
             "leftMaxForce": 400.0, "rightMaxForce": 360.0},
            # test for the UNRESOLVED profile → must be skipped (unmatched).
            {"testId": "t-nb2", "profileId": PID_AMB, "testTypeName": "Nordic",
             "testDateUtc": "2026-05-06T09:00:00Z", "modifiedDateUtc": "2026-05-06T09:00:00Z",
             "leftMaxForce": 100.0, "rightMaxForce": 100.0},
        ])
        report = self._run()
        self.assertEqual(report["created"], 1)
        self.assertEqual(report["unmatched"], 1)
        r = ExamResult.objects.get(player=self.charles, template__slug="nordico")
        self.assertEqual(r.result_data["left_max"], 400.0)
        self.assertEqual(r.result_data["right_max"], 360.0)
        self.assertIn("imbalance", r.result_data)  # calculated

    # -- dedup + gating -----------------------------------------------------

    def test_dedup_on_rerun(self):
        nb = [{"testId": "t-nb", "profileId": PID_NAME, "testTypeName": "Nordic",
               "testDateUtc": "2026-05-06T09:00:00Z", "modifiedDateUtc": "2026-05-06T09:00:00Z",
               "leftMaxForce": 400.0, "rightMaxForce": 360.0}]
        self._configure(nb=nb)
        first = self._run(full=True)
        self.assertEqual(first["created"], 1)
        self._configure(nb=nb)
        second = self._run(full=True)
        self.assertEqual(second["created"], 0)
        self.assertEqual(second["skipped"], 1)
        self.assertEqual(ExamResult.objects.filter(player=self.charles, template__slug="nordico").count(), 1)

    def test_disabled_integration_skips(self):
        self.integ.enabled = False
        self.integ.save()
        report = self._run()
        self.assertEqual(report["status"], "skipped")

    def test_product_toggle_disables_ingest(self):
        self.integ.sync_nordbord = False
        self.integ.save()
        self._configure(nb=[
            {"testId": "t-nb", "profileId": PID_NAME, "testTypeName": "Nordic",
             "testDateUtc": "2026-05-06T09:00:00Z", "modifiedDateUtc": "2026-05-06T09:00:00Z",
             "leftMaxForce": 400.0, "rightMaxForce": 360.0}],
        )
        self._run()  # products=None → honors toggles
        self.assertEqual(ExamResult.objects.filter(template__slug="nordico").count(), 0)
        # ...but an explicit --product bypasses the toggle.
        self._configure(nb=[
            {"testId": "t-nb", "profileId": PID_NAME, "testTypeName": "Nordic",
             "testDateUtc": "2026-05-06T09:00:00Z", "modifiedDateUtc": "2026-05-06T09:00:00Z",
             "leftMaxForce": 400.0, "rightMaxForce": 360.0}],
        )
        self._run(products=("nordbord",))
        self.assertEqual(ExamResult.objects.filter(template__slug="nordico").count(), 1)

    def test_template_slug_override(self):
        # Point Nordic at a differently-slugged template and confirm it feeds it.
        from exams.models import ExamTemplate
        nordico = ExamTemplate.objects.get(slug="nordico", department__club=self.club)
        nordico.slug = "nordico_custom"
        nordico.save()
        self.integ.nordico_template_slug = "nordico_custom"
        self.integ.save()
        self._configure(nb=[
            {"testId": "t-nb", "profileId": PID_NAME, "testTypeName": "Nordic",
             "testDateUtc": "2026-05-06T09:00:00Z", "modifiedDateUtc": "2026-05-06T09:00:00Z",
             "leftMaxForce": 400.0, "rightMaxForce": 360.0}],
        )
        report = self._run()
        self.assertEqual(report["created"], 1)
        self.assertEqual(
            ExamResult.objects.filter(template__slug="nordico_custom").count(), 1,
        )

    def test_dry_run_writes_nothing(self):
        self._configure(nb=[
            {"testId": "t-nb", "profileId": PID_NAME, "testTypeName": "Nordic",
             "testDateUtc": "2026-05-06T09:00:00Z", "modifiedDateUtc": "2026-05-06T09:00:00Z",
             "leftMaxForce": 400.0, "rightMaxForce": 360.0}],
        )
        report = self._run(dry_run=True)
        self.assertEqual(report["created"], 1)  # would-create count
        self.assertEqual(ExamResult.objects.filter(player=self.charles).count(), 0)
        self.assertEqual(ValdProfileLink.objects.filter(club=self.club).count(), 0)
