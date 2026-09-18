"""Fast unit tests for the current DP1 multi-AI-data evaluator."""
from __future__ import annotations
import unittest
from pathlib import Path

from model import DataObject, load_system, DATA_CLASSES
from policies import ResourceStateMonitor, Telemetry, DataClassifier
from scenarios import scenarios, generate_trace

CONFIG_DIR=Path(__file__).resolve().parents[1]/"configs"

class DP1EvalTests(unittest.TestCase):
    def test_reference_config_loads_all_six_memories(self):
        system=load_system(CONFIG_DIR)
        self.assertEqual(system.model.name,"llama_3_1_70b")
        self.assertEqual(set(system.memories),{"hbm","custom_hbm","cxl_pnm","dram","hbf","ssd_pim"})
        self.assertEqual(system.memories["hbm"].capacity_bytes,206158430208*8)
        self.assertAlmostEqual(system.memories["hbm"].ext_bw,8e12*8)

    def test_scenario_suite_covers_all_ai_data_classes(self):
        covered=set()
        names=set()
        for s in scenarios():
            names.add(s.name); covered.update(s.data_mix)
        self.assertGreaterEqual(len(names),20)
        self.assertEqual(covered,set(DATA_CLASSES))
        for required in {"steady_hot_kv","rag_hot_cold_index","agent_memory_long_lived",
                         "runtime_log_append","lora_multi_tenant","moe_expert_skew",
                         "mixed_all_ai_data","classifier_error","six_tier_stress"}:
            self.assertIn(required,names)

    def test_six_tier_stress_declares_all_target_tiers(self):
        s=next(x for x in scenarios() if x.name=="six_tier_stress")
        self.assertEqual(set(s.target_tiers),{"hbm","custom_hbm","cxl_pnm","dram","hbf","ssd_pim"})

    def test_resource_monitor_predicts_trend(self):
        m=ResourceStateMonitor(window=5,horizon=2)
        for p in (.2,.3,.4):
            m.observe({"hbm":Telemetry(capacity_util=p)})
        pred=m.state("hbm",Telemetry(capacity_util=.4))
        self.assertGreater(pred.predicted_pressure,pred.current_pressure)

    def test_c2_classifier_uses_descriptor_hint(self):
        c=DataClassifier()
        obj=DataObject(1,"KV_CACHE",1.0,1.0,1.0,2048,16,10,type_hint="RAG_DATA")
        self.assertEqual(c.classify(obj),"RAG_DATA")

    def test_same_seed_generates_same_trace(self):
        s=next(x for x in scenarios() if x.name=="mixed_all_ai_data")
        a=generate_trace(s,11); b=generate_trace(s,11)
        self.assertEqual([(x.data_class,x.size_bytes,x.arrival_s,x.base_rate,x.type_hint) for x in a],
                         [(x.data_class,x.size_bytes,x.arrival_s,x.base_rate,x.type_hint) for x in b])

    def test_runtime_log_is_not_sstable_scenario(self):
        s=next(x for x in scenarios() if x.name=="runtime_log_append")
        self.assertEqual(s.data_mix,{"LOG_DATA":1})
        self.assertIn("Not SST",s.description)

if __name__=="__main__": unittest.main()
