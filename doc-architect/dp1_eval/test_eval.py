"""Fast unit tests for the current DP1 evaluator."""
from __future__ import annotations

import unittest
from pathlib import Path

from model import DataObject, load_system, DATA_CLASSES
from policies import (
    ResourceStateMonitor, RuntimeStateMonitor, Telemetry,
    DataClassifier, SafeFallbackSelector
)
from scenarios import scenarios, generate_trace

CONFIG_DIR=Path(__file__).resolve().parents[1]/"configs"

class DP1EvalTests(unittest.TestCase):
    def test_reference_config_loads_all_six_memories(self):
        system=load_system(CONFIG_DIR)
        self.assertEqual(system.model.name,"llama_3_1_70b")
        self.assertEqual(set(system.memories),{"hbm","custom_hbm","cxl_pnm","dram","hbf","ssd_pim"})
        self.assertEqual(system.memories["hbm"].capacity_bytes,206158430208*8)
        self.assertAlmostEqual(system.memories["hbm"].ext_bw,8e12*8)

    def test_scenario_suite_covers_primary_ai_data_classes(self):
        covered=set()
        names=set()
        for s in scenarios():
            names.add(s.name); covered.update(s.data_mix)
        self.assertGreaterEqual(len(names),20)
        self.assertEqual(covered,set(DATA_CLASSES))
        for required in {
            "kv_b256_c128k_burst","kv_b64_c512k_long",
            "rag_8tib_b64_ssd_pim","rag_8tib_b256_ssd_pim",
            "agent_memory_long_lived","lora_multi_tenant_b64",
            "moe_expert_skew_b256","mixed_all_ai_data_b64",
            "classifier_error","kv_mispredict_dram_wait","six_tier_capacity_stress",
        }:
            self.assertIn(required,names)

    def test_large_batch_and_long_context_present(self):
        self.assertTrue(any(s.batch_size>=256 for s in scenarios()))
        self.assertTrue(any(s.context_tokens>=524288 for s in scenarios()))

    def test_six_tier_stress_declares_all_target_tiers(self):
        s=next(x for x in scenarios() if x.name=="six_tier_capacity_stress")
        self.assertEqual(set(s.target_tiers),{"hbm","custom_hbm","cxl_pnm","dram","hbf","ssd_pim"})

    def test_resource_monitor_predicts_trend(self):
        m=ResourceStateMonitor(window=5,horizon=2)
        for p in (.2,.3,.4):
            m.observe({"hbm":Telemetry(capacity_util=p)})
        pred=m.state("hbm",Telemetry(capacity_util=.4))
        self.assertGreater(pred.predicted_pressure,pred.current_pressure)

    def test_c2_classifier_returns_hint_and_confidence(self):
        c=DataClassifier()
        obj=DataObject(1,"KV_CACHE",1.0,1.0,1.0,2048,16,10,type_hint="RAG_DATA",classification_confidence=.61)
        cls,conf=c.classify(obj)
        self.assertEqual(cls,"RAG_DATA")
        self.assertAlmostEqual(conf,.61)

    def test_rag_ssd_pim_is_gemv_only(self):
        system=load_system(CONFIG_DIR)
        ssd=system.memories["ssd_pim"]
        self.assertTrue(ssd.retrieval_dot_capable)
        self.assertEqual(ssd.primitives,frozenset({"GEMV"}))
        self.assertFalse(ssd.attention_capable)
        cost=system.rag_retrieval_s(128*1024**3,64,"ssd_pim",1024)
        self.assertGreater(cost,0)

    def test_custom_hbm_and_cxl_support_full_attention(self):
        system=load_system(CONFIG_DIR)
        self.assertTrue(system.memories["custom_hbm"].attention_capable)
        self.assertTrue(system.memories["cxl_pnm"].attention_capable)
        self.assertFalse(system.memories["ssd_pim"].attention_capable)

    def test_safe_fallback_prefers_hbm_for_active_kv_when_healthy(self):
        system=load_system(CONFIG_DIR)
        f=SafeFallbackSelector(system)
        obj=DataObject(1,"KV_CACHE",4*1024**3,.1,1.0,32768,64,100,batch_size=64)
        tele={n:Telemetry(.1,.1) for n in system.memories}
        tier,mode=f.decide(obj,tele,1.0,{"next_reuse_s":1.0},float("inf"))
        self.assertEqual(tier,"hbm")
        self.assertEqual(mode,"immediate_hbm")

    def test_runtime_monitor_uses_observed_accesses(self):
        m=RuntimeStateMonitor()
        obj=DataObject(7,"KV_CACHE",1.0,.1,1.0,2048,16,100)
        m.observe(obj,0,0)
        m.observe(obj,2,1)
        m.observe(obj,0,2)
        m.observe(obj,1,4)
        st=m.stats(obj)
        self.assertGreater(st["rate"],0)
        self.assertGreater(st["samples"],0)
        self.assertTrue(st["reuse_interval_s"]>=1.0)

    def test_same_seed_generates_same_trace(self):
        s=next(x for x in scenarios() if x.name=="mixed_all_ai_data_b64")
        a=generate_trace(s,11); b=generate_trace(s,11)
        self.assertEqual(
            [(x.data_class,x.size_bytes,x.arrival_s,x.base_rate,x.type_hint,x.batch_size) for x in a],
            [(x.data_class,x.size_bytes,x.arrival_s,x.base_rate,x.type_hint,x.batch_size) for x in b])

if __name__=="__main__":
    unittest.main()
