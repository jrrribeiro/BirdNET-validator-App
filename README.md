# BirdNET Validator HF App

Aplicacao de validacao de deteccoes para Hugging Face Spaces (Gradio), com foco em:
- Multi-projeto
- Audio sob demanda
- Persistencia de validacoes
- Escalabilidade para datasets grandes

## Desenvolvimento local
1. Criar ambiente virtual Python 3.11+
2. Instalar dependencias:
   pip install -r requirements.txt
3. Rodar app:
   python app.py

## CLI de dataset (Sprint 1)
Comandos principais:

1. Criar estrutura do projeto no dataset Hugging Face:
   python -m cli.hf_dataset_cli create-project --project-slug ppbio-rabeca --dataset-repo USUARIO/birdnet-ppbio-rabeca-dataset

2. Gerar manifesto e shards iniciais de indice:
   python -m cli.hf_dataset_cli build-index --project-slug ppbio-rabeca --dataset-repo USUARIO/birdnet-ppbio-rabeca-dataset --detections-file detections.csv --shard-size 10000

3. Fazer upload de audio em lotes com retry e resume:
   python -m cli.hf_dataset_cli sync-audio --project-slug ppbio-rabeca --dataset-repo USUARIO/birdnet-ppbio-rabeca-dataset --local-audio-dir ./audio --batch-size 100 --max-retries 3 --resume-state-file .sync-audio-state.json

4. Verificar consistencia basica do projeto:
   python -m cli.hf_dataset_cli verify-project --project-slug ppbio-rabeca --dataset-repo USUARIO/birdnet-ppbio-rabeca-dataset

Estrutura base criada por projeto/dataset:
- audio/
- index/
- index/shards/
- validations/
- audit/
- manifest.json

## Estrutura
- src/domain: modelos de dominio
- src/repositories: contratos de persistencia
- src/services: servicos de aplicacao
- src/auth: autenticacao e autorizacao
- src/ui: montagem da interface
- src/cache: cache efemero local
- cli: comandos de ingestao/publicacao
- tests: testes unitarios e integracao

## Estado atual de implementacao
- Sprint 1: CLI create-project, sync-audio, build-index, verify-project
- Sprint 2 (inicial): fila paginada de deteccoes com filtros basicos em demo local Gradio
- Sprint 2 (backend): AudioFetchService com download sob demanda por audio_id + cache efemero com cleanup pos-validacao
- Sprint 2 (UI): carregar audio da deteccao selecionada e limpar cache apos validacao
- Sprint 2 (UI fluxo): botoes de validacao rapida com salvamento em memoria e limpeza automatica do cache de audio
- Sprint 3 (inicial): persistencia append-only de validacoes em eventos JSONL + snapshot current por detection_key
- Sprint 3 (UI): tabela exibe status atual da validacao por detection_key e botao de relatorio por projeto
- Sprint 3 (concorrencia): controle otimista por versao esperada com deteccao de conflito e bloqueio de sobrescrita silenciosa
- Sprint 3 (UX conflito): refresh automatico da tabela em conflito e foco na deteccao impactada para resolucao rapida
