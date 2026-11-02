# PASSO 82 — integração sintética de origem administrativa

## Escopo e estado de produção

Integração validada exclusivamente em aplicações TestClient criadas pelos testes.
Nenhum serviço de produção foi alterado e nenhum router foi publicado em app.main.
Infraestrutura aprovada: Admin estático HostGator, API no Render existente,
Firestore existente. A proposta histórica do PASSO 78 com Netlify/Worker não é
a arquitetura aprovada. O PASSO 79 foi relatado no chat, sem documento específico.

O usuário informou que o suporte Render recomenda CF-Connecting-IP, mas não
confirmou sobrescrita de valores falsificados, tratamento de duplicados ou
igualdade das garantias em domínio personalizado e onrender.com. Estes testes
NÃO suprem essa evidência operacional e não autorizam publicação.

## Contrato reutilizado

resolve_cf_connecting_ip(request.scope['headers']) recebe os pares ASGI brutos,
sem colapsar duplicados. Exige um único header case-insensitive e literal IP
válido; normaliza IPv6 e IPv4 mapeado. Permite espaços/tabs externos HTTP, mas
rejeita espaços internos, listas, zonas, portas explícitas e controles/injeção.
Um literal IPv6 terminado em :443 pode ser endereço válido, não porta explícita.
Não usa Origin, XFF, X-Real-IP ou request.client.host como fallback.

compose_admin_http já aceita trusted_origin_dependency. Não é necessário mudar
o contrato nem criar outro parser. O adaptador synthetic_origin existe SOMENTE
no arquivo de testes. Por padrão recusa a origem mesmo com CF sintaticamente
válido. Sua aprovação explícita é uma premissa sintética em memória, nunca uma
variável de ambiente, header de aprovação ou atestação do Render. Não copiá-lo
como provedor de produção. O runner HTTPS local permanece inalterado e continua
utilizando seu contrato exclusivo de conexão loopback.

Sem dependência adequada, o login composto permanece 503. Falha de resolução
ocorre antes da admissão e autenticação, sem consultar o armazenamento. Falha
da admissão impede Argon2/sessão. Origin/CSRF continuam sendo controles distintos.

## Testes e limites da simulação

test_admin_origin_composition.py reutiliza fixtures e fábrica existentes.
Transações são as da infraestrutura isolada em memória: não demonstram
contenção, retries ou comportamento do Firestore real. A consulta indexada por
e-mail é um mock porque esse fake não suporta queries. Verificação Argon2id,
repositório de admissão, política inicial, serviço de autenticação e ciclo de
sessões usam implementações existentes. Nenhuma credencial real é carregada;
fixtures proíbem inicialização Firebase real.

Cobertura adicional: ausência/vazio/malformação/listas/duplicados/injeção,
IPv4/IPv6/mapeados/canonicalização, XFF sob middleware Uvicorn com confiança '*',
recusa de fronteira não aprovada, ausência de fallback, indisponibilidade da
admissão, cinco falhas de senha e sexta tentativa limitada, login válido,
sessão, CSRF e logout com revogação e mensagens sem dados sensíveis.

O teste de troca de CF demonstra uma limitação deliberadamente: quando a fixture
ASSUME uma fronteira aprovada, outro CF válido cria novos buckets. O parser não
detecta falsificação. Trocar XFF mantendo CF ou trocar IPv4 por sua representação
mapeada NÃO cria novo orçamento. Aprovação sintética não resolve procedência.

## Defesa complementar — proposta, NÃO implementada ou aprovada

Os buckets atuais são origem (10, +1/30s) e origem/identidade (5, +1/60s), com
admissão atômica. Não existe orçamento independente por identidade. Preservá-los.

Para avaliação futura, um orçamento agregado distribuído pode impor um teto ao
trabalho Argon2 mesmo com IPs controlados/rotativos. Candidato de ensaio, NÃO
limite de produção: capacidade 10, reposição 1/30s para todo o login administrativo.
Reutiliza como ponto de partida o orçamento hoje aprovado para uma origem, mas
compartilhá-lo entre todos altera a disponibilidade e exige medir carga/latência.
Um orçamento adicional por identidade, candidato capacidade 5 e +1/60s, reduz
ataques distribuídos contra um e-mail, mas permite ao atacante consumir o acesso
da vítima. Não recomendar sua ativação sem decisão explícita sobre esse risco.
Nenhum dos dois equivale à procedência IP ou garante disponibilidade sob ataque.

Uma eventual implementação precisaria admitir todos os orçamentos numa única
transação ANTES da senha, sem liberação paralela fora do limite, sem reset por
sucesso e sem bloqueio permanente/Admin.status. Identificadores HMAC separados
por finalidade, relógio servidor e falha fechada devem ser mantidos. Não adaptar
o contrato atual passando uma origem constante nem migrar registros neste passo.

Custos incrementais de desenho: um bucket agregado adiciona uma leitura por
admissão e uma escrita por admissão permitida; adicionar identidade independente
adiciona mais uma de cada, além das duas atuais, conforme implementação final.
Retentativas podem ampliar leituras. Rejeições ainda custam leituras; bucket
agregado concentra contenção, identidade arbitrária pode ampliar cardinalidade.
Não há estimativa monetária confiável sem volume, região e projeto/franquia.
Não exige contratar serviço, mas não promete custo Firestore zero.

Testes necessários antes de aprovar: múltiplas instâncias/identidades/IPs,
concorrência e teto agregado, identidade vítima sob ataque, esgotamento e
recuperação, partilha justa entre administradores, enumeração, Firestore
indisponível/commit incerto, cardinalidade, custo e contenção sob carga limitada.

## Pendências e próximo passo

Manter Admin não publicado. Confirmar contrato de ingresso Render e aprovar
explicitamente o provedor; não inferir confiança por Host, RENDER=true ou cookie.
Se a procedência continuar sem garantia, decidir separadamente se a proposta
complementar atende ao risco aceito, incluindo negação de serviço. Não converter
essa alternativa em redução silenciosa dos requisitos de entrada existentes.
Domínios finais, HTTPS/cookies/CORS reais, IAM/índices e operação de produção
continuam sujeitos à homologação autorizada. Kirvano e regras comerciais intactos.
Não iniciar PASSO 83 automaticamente.

## Comandos de validação isolada

Na raiz do projeto:

```sh
PYTHONDONTWRITEBYTECODE=1 Backend/.venv/bin/python -m pytest -q -p no:cacheprovider Backend/tests/test_admin_origin_composition.py
PYTHONDONTWRITEBYTECODE=1 Backend/.venv/bin/python -m pytest -q -p no:cacheprovider Backend/tests
git diff --check
```

Não usar --run-firestore-emulator para esta validação: a fixture histórica de
integração limpa globalmente o banco. Nenhum teste deste passo necessita emulator
ou toca nos dados sintéticos existentes e nenhum servidor precisa ser encerrado.

Resultados: 19 novos cenários aprovados; conjunto específico 209 aprovados;
suíte completa 1.255 aprovados e 52 subtestes aprovados, 218 testes de integração
desselecionados. As contagens se sobrepõem e não devem ser somadas. Nenhuma falha
final; aviso existente de depreciação TestClient/httpx, sem instalar dependências.
Na primeira execução, sete casos falharam por ausência de suporte a queries no
fake reutilizado; foi corrigida somente a montagem do teste com mock de lookup,
não o código de produção. Os 19 casos passaram após esse ajuste.
