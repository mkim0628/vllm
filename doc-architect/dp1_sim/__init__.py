"""DP1 배치 정책 시뮬레이터.

설계 문서: ../dp1-heterogeneous-memory-data-placement.md
구현 UML:  ../dp1-implementation-uml.md

문서의 평가 가정(§11)은 이 구현에서 재사용하지 않는다. 물리 모델(§4)과
Configuration(§3.4)만 가져오고, 워크로드·시나리오·판정 기준은
workload.py / run_eval.py 에서 독립적으로 정의한다.
"""
