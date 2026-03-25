# GitHub Issues - BirdNET Validator HF

Use este arquivo como roteiro para abrir as issues no novo repositorio do app.
Sugestao: criar milestones por sprint e labels por tipo.

## Labels sugeridas
- epic
- p0
- p1
- backend
- frontend
- infra
- data
- auth
- performance
- testing

## Milestones sugeridas
- Sprint 0 - Preparacao
- Sprint 1 - Ingestao e indice
- Sprint 2 - Core leitura e cache
- Sprint 3 - Persistencia colaborativa
- Sprint 4 - Seguranca multi-projeto
- Sprint 5 - UX e performance
- Sprint 6 - Operacao e qualidade

## Issue 01 - Bootstrap do repositorio e CI minima
Title: [Sprint 0][P0] Bootstrap do repositorio birdnet-validator-hf-app
Labels: epic, p0, infra
Milestone: Sprint 0 - Preparacao
Body:
- Objetivo: inicializar o novo repositorio com estrutura base, lint, testes e pipeline minima.
- Tarefas:
  - Criar estrutura src, tests, docs, cli.
  - Adicionar pyproject.toml e requirements.
  - Adicionar pre-commit (opcional) e GitHub Actions para teste.
  - Subir app Gradio minimo com tela placeholder.
- Criterios de aceite:
  - Repo roda local sem erro.
  - CI executa em PR.
  - README inicial com setup local.

## Issue 02 - Modelos de dominio e validacao de schema
Title: [Sprint 0][P0] Definir modelos de dominio e schema
Labels: p0, backend, data
Milestone: Sprint 0 - Preparacao
Body:
- Objetivo: criar modelos Project, Detection, Validation, User, Role, IndexManifest.
- Tarefas:
  - Implementar modelos com dataclass/pydantic.
  - Incluir validacoes de campos obrigatorios.
  - Fixar versao do schema para evolucao futura.
- Criterios de aceite:
  - Testes unitarios de validacao passam.
  - Modelos serializam/deserializam sem perda.

## Issue 03 - Contratos de repositorio e fake adapters
Title: [Sprint 0][P0] Criar contratos de repositorio e adapters fake
Labels: p0, backend
Milestone: Sprint 0 - Preparacao
Body:
- Objetivo: desacoplar UI da persistencia desde o inicio.
- Tarefas:
  - Definir interfaces: ProjectRepository, DetectionRepository, ValidationRepository, AuthRepository.
  - Implementar adapters fake para testes locais.
- Criterios de aceite:
  - Casos basicos funcionam sem HF remoto.
  - Cobertura minima dos contratos.

## Issue 04 - CLI create-project para dataset HF
Title: [Sprint 1][P0] Implementar comando create-project
Labels: p0, backend, data
Milestone: Sprint 1 - Ingestao e indice
Body:
- Objetivo: criar estrutura do dataset por projeto no Hugging Face.
- Tarefas:
  - Criar comando create-project.
  - Estrutura inicial: audio, index, validations, audit, manifest.json.
- Criterios de aceite:
  - Estrutura criada corretamente em dataset novo.
  - Comando idempotente quando projeto ja existe.

## Issue 05 - CLI sync-audio com resume e retry
Title: [Sprint 1][P0] Upload de audio em lotes com resume idempotente
Labels: p0, backend, data, performance
Milestone: Sprint 1 - Ingestao e indice
Body:
- Objetivo: subir audios sem depender de fluxo Git LFS local.
- Tarefas:
  - Implementar sync-audio em lotes.
  - Retry com backoff e resume por checkpoint.
  - Log transacional por lote.
- Criterios de aceite:
  - Falha de rede nao duplica uploads.
  - Retomada completa apos interrupcao.

## Issue 06 - CLI build-index e checksums
Title: [Sprint 1][P0] Gerar index_manifest e shards de deteccao
Labels: p0, data, backend
Milestone: Sprint 1 - Ingestao e indice
Body:
- Objetivo: permitir leitura paginada rapida no app.
- Tarefas:
  - Gerar manifest.json com estatisticas.
  - Gerar shards de deteccoes e checksums.
- Criterios de aceite:
  - Manifesto referencia apenas artefatos existentes.
  - Validacao de integridade passa.

## Issue 07 - CLI verify-project
Title: [Sprint 1][P0] Verificador de consistencia do projeto
Labels: p0, data, testing
Milestone: Sprint 1 - Ingestao e indice
Body:
- Objetivo: validar consistencia audio x index x deteccoes.
- Tarefas:
  - Implementar comando verify-project.
  - Emitir relatorio com erros e warnings.
- Criterios de aceite:
  - Retorna codigo de erro em inconsistencias.

## Issue 08 - Fila paginada de deteccoes
Title: [Sprint 2][P0] Implementar detection queue paginada
Labels: p0, backend, performance
Milestone: Sprint 2 - Core leitura e cache
Body:
- Objetivo: navegar grandes volumes sem travar UI.
- Tarefas:
  - API interna de pagina com filtros.
  - Ordenacao estavel e cursor/offset.
- Criterios de aceite:
  - Navega 50k deteccoes com fluidez.

## Issue 09 - Download sob demanda por audio_id
Title: [Sprint 2][P0] AudioFetchService para arquivo individual
Labels: p0, backend, performance
Milestone: Sprint 2 - Core leitura e cache
Body:
- Objetivo: baixar somente audio da deteccao ativa.
- Tarefas:
  - Implementar fetch por audio_id.
  - Tratamento de erro e retry curto.
- Criterios de aceite:
  - Nenhum preload global do dataset.

## Issue 10 - Cache efemero e cleanup apos validacao
Title: [Sprint 2][P0] Implementar cache LRU TTL e limpeza pos-validacao
Labels: p0, backend, performance
Milestone: Sprint 2 - Core leitura e cache
Body:
- Objetivo: reduzir custo e memoria mantendo comportamento seguro.
- Tarefas:
  - Cache em RAM e /tmp com limite configuravel.
  - Cleanup apos salvar validacao.
- Criterios de aceite:
  - Temporario removido apos validacao.
  - Arquivo remoto permanece intacto.

## Issue 11 - Persistencia append-only de validacoes
Title: [Sprint 3][P0] Log append-only de eventos de validacao
Labels: p0, backend, data
Milestone: Sprint 3 - Persistencia colaborativa
Body:
- Objetivo: garantir trilha auditavel completa.
- Tarefas:
  - Salvar eventos em shards por data.
  - Incluir usuario, status anterior/novo, timestamp, notas.
- Criterios de aceite:
  - Toda alteracao gera evento auditavel.

## Issue 12 - Snapshot current por detection_key
Title: [Sprint 3][P0] Materializar estado atual de validacoes
Labels: p0, backend, data, performance
Milestone: Sprint 3 - Persistencia colaborativa
Body:
- Objetivo: acelerar leitura do estado mais recente.
- Tarefas:
  - Consolidar eventos em current.parquet.
- Criterios de aceite:
  - Lookup por detection_key em baixa latencia.

## Issue 13 - Concorrencia otimista e merge de conflito
Title: [Sprint 3][P0] Controle de concorrencia para validadores simultaneos
Labels: p0, backend
Milestone: Sprint 3 - Persistencia colaborativa
Body:
- Objetivo: evitar perda silenciosa de dados.
- Tarefas:
  - Implementar revisao/etag.
  - Definir merge deterministico de conflitos.
- Criterios de aceite:
  - Nao ha perda de validacao em concorrencia.

## Issue 14 - Login e sessao com papeis
Title: [Sprint 4][P0] AuthService com usuarios e papeis
Labels: p0, auth, backend
Milestone: Sprint 4 - Seguranca multi-projeto
Body:
- Objetivo: controlar acesso ao app e por projeto.
- Tarefas:
  - Login e sessao segura.
  - Papel admin e validator.
- Criterios de aceite:
  - Usuario sem permissao nao acessa projeto indevido.

## Issue 15 - ACL por projeto
Title: [Sprint 4][P0] Isolamento de acesso por projeto
Labels: p0, auth, backend
Milestone: Sprint 4 - Seguranca multi-projeto
Body:
- Objetivo: evitar vazamento entre projetos.
- Tarefas:
  - Enforcar filtro por projeto em todas consultas.
- Criterios de aceite:
  - Dados de um projeto nao aparecem em outro.

## Issue 16 - Painel Admin multi-projeto
Title: [Sprint 4][P0] UI admin para projetos e membros
Labels: p0, frontend, auth
Milestone: Sprint 4 - Seguranca multi-projeto
Body:
- Objetivo: operar ambiente sem editar codigo.
- Tarefas:
  - Criar/arquivar projeto.
  - Atribuir usuarios por projeto.
  - Mostrar progresso por projeto.
- Criterios de aceite:
  - Alteracoes ficam disponiveis para novas sessoes.

## Issue 17 - Fluxo rapido de validacao
Title: [Sprint 5][P1] Acoes rapidas com auto-avanco
Labels: p1, frontend
Milestone: Sprint 5 - UX e performance
Body:
- Objetivo: aumentar throughput humano.
- Tarefas:
  - Positivo/Negativo/Indeterminado/Pular com 1 clique.
- Criterios de aceite:
  - Apos salvar, app avanca automaticamente.

## Issue 18 - Filtros compostos
Title: [Sprint 5][P1] Filtros por especie confianca status localidade data
Labels: p1, frontend, backend
Milestone: Sprint 5 - UX e performance
Body:
- Objetivo: melhorar foco de validacao.
- Criterios de aceite:
  - Combinacao de filtros retorna resultados corretos.

## Issue 19 - Recuperacao de sessao
Title: [Sprint 5][P1] Restaurar ultimo contexto do usuario
Labels: p1, frontend
Milestone: Sprint 5 - UX e performance
Body:
- Objetivo: evitar perda de contexto ao recarregar.
- Criterios de aceite:
  - Ultimo item e filtros principais restaurados.

## Issue 20 - Prefetch curto de audio
Title: [Sprint 5][P1] Prefetch de N proximos audios
Labels: p1, performance, backend
Milestone: Sprint 5 - UX e performance
Body:
- Objetivo: reduzir latencia do proximo item.
- Criterios de aceite:
  - Melhora p95 sem extrapolar limite de cache.

## Issue 21 - Logs estruturados
Title: [Sprint 6][P1] Logging estruturado com correlacao
Labels: p1, infra
Milestone: Sprint 6 - Operacao e qualidade
Body:
- Objetivo: facilitar observabilidade e suporte.
- Criterios de aceite:
  - Erros rastreaveis por usuario/projeto/request.

## Issue 22 - Metricas e painel operacional
Title: [Sprint 6][P1] Metricas de latencia erro throughput
Labels: p1, performance, frontend
Milestone: Sprint 6 - Operacao e qualidade
Body:
- Objetivo: monitorar saude do sistema em producao.
- Criterios de aceite:
  - p50/p95 e taxa de erro visiveis no admin.

## Issue 23 - Testes de integracao e carga basica
Title: [Sprint 6][P1] Suite minima de qualidade para release
Labels: p1, testing
Milestone: Sprint 6 - Operacao e qualidade
Body:
- Objetivo: reduzir regressao antes de producao.
- Criterios de aceite:
  - CI verde com testes unitarios e integracao.

## Dependencias recomendadas entre issues
- 01 -> 02 -> 03
- 03 -> 08, 09, 10, 11, 14
- 04, 05, 06 -> 07
- 06, 08 -> 09
- 09 -> 10 -> 20
- 11 -> 12 -> 13
- 14 -> 15 -> 16
- 08, 12, 14, 15 -> 17, 18, 19
- Todas P0 -> 21, 22, 23

## Checklist de fechamento da v1
- [ ] Upload CLI funcional para projetos grandes
- [ ] Index paginado publicado por projeto
- [ ] Audio sob demanda com cleanup local
- [ ] Validacao colaborativa com auditoria
- [ ] ACL por projeto e painel admin
- [ ] Metricas e testes minimos em CI
