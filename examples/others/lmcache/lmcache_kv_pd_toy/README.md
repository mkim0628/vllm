# LMCache KV Connector 기반 Prefill/Decode Disaggregation Toy Project

이 예제는 `vllm serve` 를 **Prefiller(Producer)** 와 **Decoder(Consumer)** 로 분리 실행하고,
Prefiller가 만든 KV cache 메타데이터(`kv_transfer_params`)를 Proxy가 받아 Decoder 요청에 전달하는 최소 구성입니다.

## 구성

- Prefiller: `LMCacheConnectorV1 + kv_producer`
- Decoder: `LMCacheConnectorV1 + kv_consumer`
- Proxy: 클라이언트 요청을 받아
  1) Prefiller에 비스트리밍 요청(`max_tokens=1`) 전송
  2) 응답 JSON의 `kv_transfer_params` 추출
  3) Decoder 요청 body에 `kv_transfer_params`를 주입해서 스트리밍 전달

## 사전 요구사항

- GPU 2개 이상
- `vllm`, `lmcache`, `fastapi`, `uvicorn`, `httpx` 설치
- (NIXL 전송 사용 시) `nixl` 설치
- Hugging Face 모델 접근 권한(`HF_TOKEN`)

## 실행

아래 스크립트는 Prefiller(8100), Decoder(8200), Proxy(9000)를 띄웁니다.

```bash
cd examples/others/lmcache/lmcache_kv_pd_toy
bash run_toy.sh
```

기본 모델은 `meta-llama/Llama-3.1-8B-Instruct` 이며,
`MODEL_NAME` 환경 변수로 변경할 수 있습니다.

## 테스트 요청

```bash
curl -N http://127.0.0.1:9000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "meta-llama/Llama-3.1-8B-Instruct",
    "messages": [{"role":"user","content":"vLLM disaggregation 동작을 한 줄로 설명해줘."}],
    "stream": true,
    "max_tokens": 128,
    "temperature": 0.1
  }'
```

## 핵심 포인트

`proxy_server.py`의 `run_prefill_then_attach_kv()` 가 핵심입니다.

- Prefill 응답에서 `kv_transfer_params`를 꺼냅니다.
- 해당 값을 decode 요청에 그대로 주입합니다.
- 즉, **Prefiller에서 생성된 KV cache 식별 정보가 Decoder로 전달**됩니다.

### `kv_transfer_params`에 실제 KV 텐서가 들어가나요?

아니요. 일반적으로 `kv_transfer_params`는 **실제 KV 텐서 자체**가 아니라,
커넥터가 원격 KV를 찾거나 전송/수신을 조율하기 위한 **메타데이터**(예: 엔진/블록 식별자,
핸드셰이크 정보, 전송 플래그)입니다.

실제 KV 텐서 저장/전송은 KV Connector 경로에서 수행됩니다.

- Worker 측: `start_load_kv`, `save_kv_layer`, `wait_for_save` 등을 통해 KV를 송수신
- Scheduler 측: 요청 종료 시 connector가 반환한 파라미터가 출력의
  `kv_transfer_params`로 노출될 수 있음

즉 이 toy proxy는 KV 텐서를 옮기는 코드가 아니라,
**prefill 단계에서 생성된 전송 메타데이터(`kv_transfer_params`)를 decode 단계로 전달**하는 역할입니다.

## 참고

- LMCache의 전송 설정 YAML은 기존 예제의 파일을 재사용합니다.
  - `examples/others/lmcache/disagg_prefill_lmcache_v1/configs/lmcache-prefiller-config.yaml`
  - `examples/others/lmcache/disagg_prefill_lmcache_v1/configs/lmcache-decoder-config.yaml`
