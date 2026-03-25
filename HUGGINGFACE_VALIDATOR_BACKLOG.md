# BirdNET Validator HF - Backlog Executavel

## 1) Objetivo
Construir um novo app de validacao de deteccoes BirdNET para Hugging Face Spaces (Gradio), reutilizavel para varios projetos, com:
- Um dataset Hugging Face por projeto
- Download de audio sob demanda (1 arquivo por vez)
- Limpeza de memoria/temporario apos validacao
- Sem remover arquivos no dataset remoto
- Upload de dados via CLI usando API (`huggingface_hub`), sem fluxo Git LFS local
- Gestao de usuarios/papeis e isolamento por projeto

## 2) Estrategia de repositorios
### Repositorio 1 (novo): app
- Nome sugerido: `birdnet-validator-hf-app`
- Conteudo: Gradio app, servicos, auth, cache, UI, testes, docs de deploy

### Repositorios 2..N: datasets por projeto
- Nome sugerido: `birdnet-<project-slug>-dataset`
- Conteudo: `audio/`, `index/`, `validations/`, `audit/`, `manifest.json`

### Estrutura de pastas do app
```text
birdnet-validator-hf-app/
  app.py
  requirements.txt
  README.md
  src/
    domain/
    services/
    repositories/
    auth/
    ui/
    cache/
    telemetry/
  cli/
    hf_dataset_cli.py
  tests/
    unit/
    integration/
  docs/
    architecture.md
    operations.md
```

## 3) Definicoes tecnicas fechadas
- UI: Gradio no Hugging Face Space
- Armazenamento principal: Hugging Face Datasets
- Granularidade: 1 dataset por projeto
- Ingestao: CLI separada com `huggingface_hub`
- Identidade de deteccao: `detection_key` estavel e imutavel
- Leitura de audio: sob demanda por `audio_id`
- Cache local: efemero (RAM + /tmp), com limite por tamanho e TTL
- Pos-validacao: limpar buffer em memoria e arquivo temporario local
- Nunca deletar audio original do dataset remoto durante validacao

## 4) Definicao de pronto (DoD)
Uma tarefa so e considerada pronta quando:
1. Codigo implementado com testes minimos
2. Logs de erro e sucesso adicionados
3. Documentacao curta atualizada
4. Validada em ambiente local
5. Sem regressao em fluxo principal

## 5) Epics e backlog por prioridade

## Epic A - Bootstrap do novo app e arquitetura base (P0)
### A1. Criar novo repositorio do app
- Descricao: inicializar `birdnet-validator-hf-app` com estrutura base
- Entregavel: repo criado + branch strategy + CI minima
- Criterio de aceite: app sobe local com tela inicial vazia

### A2. Definir modelos de dominio
- Descricao: `Project`, `Detection`, `Validation`, `User`, `Role`, `IndexManifest`
- Entregavel: dataclasses/pydantic + validacoes de schema
- Criterio de aceite: validacao de payload passa em testes unitarios

### A3. Definir contratos de repositorio
- Descricao: interfaces para ProjectRepo, DetectionRepo, ValidationRepo, AuthRepo
- Entregavel: interfaces + implementacao fake para teste
- Criterio de aceite: casos basicos executam sem dependencia externa

## Epic B - CLI de ingestao para Hugging Face (P0)
### B1. Comando create-project
- Descricao: criar estrutura do dataset remoto por projeto
- Entregavel: comando `create-project`
- Criterio de aceite: estrutura minima criada no repo dataset

### B2. Comando sync-audio em lotes
- Descricao: upload de audios em batch com retry e resume idempotente
- Entregavel: comando `sync-audio --resume`
- Criterio de aceite: interrupcao de rede nao duplica arquivos

### B3. Comando build-index
- Descricao: gerar `manifest.json` + shards de deteccoes
- Entregavel: pasta `index/` com particoes e checksums
- Criterio de aceite: manifesto referencia somente arquivos existentes

### B4. Comando verify-project
- Descricao: checar consistencia audio x index x deteccoes
- Entregavel: relatorio de saude do projeto
- Criterio de aceite: retorna codigo de erro quando houver inconsistencias

## Epic C - Leitura paginada e audio sob demanda (P0)
### C1. Detection queue paginada
- Descricao: listar deteccoes por pagina + filtros
- Entregavel: API interna de pagina com cursor/offset
- Criterio de aceite: navegar 50k deteccoes sem travar UI

### C2. Download individual de audio
- Descricao: baixar so o audio da deteccao ativa
- Entregavel: `AudioFetchService.fetch(audio_id)`
- Criterio de aceite: sem pre-download global de dataset

### C3. Cache efemero com limpeza
- Descricao: LRU/TTL em RAM e /tmp
- Entregavel: `CacheManager` com `cleanup_after_validation()`
- Criterio de aceite: arquivo temporario removido apos salvar validacao

### C4. Prefetch curto
- Descricao: prefetch dos proximos N audios
- Entregavel: worker simples de prefetch
- Criterio de aceite: melhora p95 de carregamento sem extrapolar limite de cache

## Epic D - Persistencia de validacoes no HF Dataset (P0)
### D1. Modelo append-only de eventos
- Descricao: salvar validacoes em log de eventos por projeto
- Entregavel: `validations/events-YYYYMMDD.parquet` (ou csv shard)
- Criterio de aceite: toda alteracao gera evento auditavel

### D2. Snapshot consolidado
- Descricao: materializar estado atual por `detection_key`
- Entregavel: `validations/current.parquet`
- Criterio de aceite: lookup por detection_key em tempo baixo

### D3. Controle de concorrencia
- Descricao: controle otimista por revisao/etag
- Entregavel: rejeicao de escrita concorrente conflitante + merge rule
- Criterio de aceite: dois validadores simultaneos nao perdem dados silenciosamente

## Epic E - Auth, papeis e isolamento por projeto (P0)
### E1. Login e sessao
- Descricao: autenticar usuarios e carregar perfil/papeis
- Entregavel: AuthService + sessao segura
- Criterio de aceite: usuario sem permissao nao entra em projeto nao autorizado

### E2. ACL por projeto
- Descricao: vincular usuario a um ou mais projetos
- Entregavel: autorizacao por projeto em todas rotas de dados
- Criterio de aceite: consultas sempre filtradas por projeto autorizado

### E3. Painel admin
- Descricao: criar/arquivar projeto, atribuir usuarios, ver progresso
- Entregavel: UI admin funcional
- Criterio de aceite: alteracoes refletidas imediatamente nas sessoes novas

## Epic F - UX de validacao e produtividade (P1)
### F1. Fluxo rapido de validacao
- Descricao: botoes de acao + avancar automaticamente
- Entregavel: fluxo Positivo/Negativo/Indeterminado/Pular
- Criterio de aceite: 1 clique para validar e ir para proximo

### F2. Filtros completos
- Descricao: especie, confianca, status, localidade, data
- Entregavel: filtros combinaveis
- Criterio de aceite: filtro composto retorna lista correta

### F3. Recuperacao de sessao
- Descricao: restaurar ultimo item e filtros
- Entregavel: SessionState persistido por usuario/projeto
- Criterio de aceite: recarregar pagina nao perde contexto principal

## Epic G - Observabilidade, qualidade e operacao (P1)
### G1. Logs estruturados
- Descricao: correlacao por usuario/projeto/request
- Entregavel: logger padrao JSON
- Criterio de aceite: erro rastreavel de ponta a ponta

### G2. Metricas de performance
- Descricao: p50/p95 fetch audio, taxa erro, throughput validacoes
- Entregavel: painel simples em admin
- Criterio de aceite: metrica atualiza em tempo quase real

### G3. Testes e hardening
- Descricao: unit + integracao + testes de carga basica
- Entregavel: suite minima automatizada
- Criterio de aceite: pipeline CI verde em PR

## 6) Roadmap por sprint (2 semanas cada)

## Sprint 0 - Preparacao
- A1, A2, A3
- Saida: arquitetura base pronta + app inicia local

## Sprint 1 - Ingestao e indice
- B1, B2, B3, B4
- Saida: projeto pode ser publicado em dataset com indice valido

## Sprint 2 - Core de leitura e cache
- C1, C2, C3
- Saida: app navega deteccoes e toca audio sob demanda com limpeza local

## Sprint 3 - Persistencia colaborativa
- D1, D2, D3
- Saida: validacoes salvas com auditoria e sem perda por concorrencia

## Sprint 4 - Seguranca e multi-projeto
- E1, E2, E3
- Saida: login + ACL por projeto + admin operacional

## Sprint 5 - UX e performance
- F1, F2, F3, C4
- Saida: fluxo de validacao rapido e estavel para volume alto

## Sprint 6 - Operacao e qualidade
- G1, G2, G3
- Saida: observabilidade, testes e readiness de producao

## 7) Criticos de arquitetura (nao negociaveis)
1. Nao carregar dataset inteiro em memoria
2. Audio sempre sob demanda por item
3. Cleanup local obrigatorio apos validacao
4. detection_key imutavel
5. Isolamento forte por projeto e por usuario

## 8) Riscos e mitigacoes
- Risco: contenção ao gravar validacoes no mesmo dataset
  - Mitigacao: append-only + snapshots + micro-batches
- Risco: latencia de rede no fetch de audio
  - Mitigacao: cache efemero + prefetch curto + retries
- Risco: crescimento de custo por requests
  - Mitigacao: politicas de cache e compressao de artefatos de indice
- Risco: conflito entre validadores
  - Mitigacao: versao otimista + log de conflitos + merge deterministico

## 9) Entregaveis finais da v1
1. Repositorio do app no ar em HF Space
2. CLI funcional para publicar projetos no HF Dataset
3. Validacao multi-projeto com usuarios/papeis
4. Download individual de audio com limpeza local
5. Persistencia de validacoes com auditoria
6. Guia de operacao para onboarding de novos projetos

## 10) Proxima acao recomendada imediata
Executar Sprint 0 e Sprint 1 antes de qualquer migracao de dados historicos.
