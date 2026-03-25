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

3. Verificar consistencia basica do projeto:
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
