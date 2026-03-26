# BirdNET Validator App

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

## Objetivo desta pasta
Contem os arquivos do app de validacao para evolucao/publicacao independente.

## Fluxo recomendado (separado)
1. Uploader app (porta 7862 por padrao):
   - Rodar dry-run com CSV + pasta de segmentos
   - Rodar upload real para owner/repo do projeto
2. Validator app (porta 7860):
   - Validar deteccoes do projeto com dados ja publicados

Essa separacao evita impacto de performance na validacao durante uploads grandes.

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

5. Ingestao BirdNET por projeto (dry-run):
   python -m cli.hf_dataset_cli ingest-segments --project-slug ppbio-rabeca --dataset-repo USUARIO/birdnet-ppbio-rabeca-dataset --detections-csv detections.csv --segments-root "C:\\BirdNET Segments" --dry-run --report-file .ingest-dry-run-report.json

6. Ingestao BirdNET por projeto (upload real):
   python -m cli.hf_dataset_cli ingest-segments --project-slug ppbio-rabeca --dataset-repo USUARIO/birdnet-ppbio-rabeca-dataset --detections-csv detections.csv --segments-root "C:\\BirdNET Segments" --batch-size 200 --shard-size 10000 --max-retries 3 --retry-backoff-seconds 1.0 --resume-state-file .ingest-segments-state.json --report-file .ingest-run-report.json

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
- Sprint 3 (UX conflito+): flag visual de conflito na linha e botao para reaplicar validacao na versao atual
- Sprint 3 (UX conflito++): sinalizacao explicita com conflict_flag=CONFLICT e conflict_severity=HIGH na deteccao afetada
- Sprint 3 (UX conflito+++): filtro rapido "mostrar apenas conflitos" integrado em refresh, paginacao e acoes de validacao
- Sprint 3 (UX conflito++++): atalhos teclado para validacao rapida (1=positivo 2=negativo 3=indeterminado 4=pular R=reaplicar)
- Sprint 3 (UX conflito+++++): operacoes em lote para aprovar/rejeitar todos os conflitos em uma unica acao
- Sprint 3 (UX conflito++++++): filtros avancados por validador, status e data de atualizacao em toda a navegacao
- Sprint 3 (UX conflito+++++++): filtro de data com seletor nativo (DateTime sem hora) para reduzir erros de digitacao
