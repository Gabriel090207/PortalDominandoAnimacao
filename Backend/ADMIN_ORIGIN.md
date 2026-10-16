# Resolvedor isolado de origem administrativa

app/api/admin_origin.py pertence à camada HTTP, mas não registra endpoint,
middleware ou dependência. Não é importado pelo main nem conectado ao login,
AdminAuthService ou AdminAdmissionService. Não lê ambiente, rede, Firestore ou
request.client; não persiste dados nem produz logs.

resolve_cf_connecting_ip recebe os pares BRUTOS de headers ASGI, futuramente
request.scope["headers"]. Não passar dict ou headers já colapsados: duplicidade
precisa continuar visível. A função exige exatamente um CF-Connecting-IP,
independentemente de caixa no nome, inclusive rejeitando duplicatas idênticas
ou com um valor vazio. Também rejeita entradas que não sejam pares de bytes.

O valor deve ser um literal IPv4/IPv6 aceito por ipaddress, com até 128 bytes
brutos. Espaços/tabs HTTP externos são removidos; outros controles, listas,
hostnames, CIDR, colchetes/portas e zonas IPv6 não são aceitos. IPv6 é comprimido
e normalizado; IPv4 mapeado em IPv6 vira o IPv4 correspondente, evitando buckets
diferentes para a mesma representação de endereço. Uma sequência como
2001:db8::1:443 é IPv6 válido: não é possível tratá-la como porta por suposição.
Porta explícita [2001:db8::1]:443 é rejeitada.

Validade sintática não exige endereço público: a função não aplica política de
roteabilidade nem bloqueio por rede. Essa política, se necessária, será separada.
IP não é identidade de pessoa; VPNs, NAT e Workers podem compartilhar origens.
Não se agrupa IPv6 por /64. Não há fallback para X-Forwarded-For, X-Real-IP,
CF-Connecting-IPv6 ou peer ASGI. Ausência/ambiguidade/valor inválido resulta em
AdminOriginResolutionError com mensagem fixa, sem conteúdo dos headers ou erro
bruto do parser. O IP canonicalizado existe apenas no retorno em memória.

IMPORTANTE: headers falsificados com IP sintaticamente válido são indistinguíveis
de headers legítimos para este parser. O retorno NÃO comprova proxy confiável.
Antes de utilizá-lo em produção, confirmar operacionalmente que o ingresso
administrativo passa pela borda pública Render/Cloudflare que sobrescreve o
header, e avaliar caminhos privados/alternativos que possam contornar essa
garantia. RENDER=true, Host, presença do header e request.client reescrito pelo
Uvicorn não são atestações dessa fronteira. Não habilitar confiança por inferência.

Uma integração futura deverá falhar fechada apenas no fluxo administrativo se
não houver origem resolvida; não registrar o IP bruto nem devolver dados de
diagnóstico. Isso não exige mudança global de proxy nem deve afetar o webhook
Kirvano. Start Command e configurações de produção permanecem inalterados.

Testes: .venv/bin/python -m pytest -q tests/test_admin_origin.py.
