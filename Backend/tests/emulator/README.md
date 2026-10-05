# Firestore Emulator: somente infraestrutura de testes

O cliente Python instalado suporta FIRESTORE_EMULATOR_HOST. Os testes usam
Client diretamente com AnonymousCredentials, sem inicializar Firebase Admin.
Nenhum teste lê .env ou firebase-key.json para acessar o Emulator.

Requisitos locais: Firebase CLI e Java JDK 21. A instalação desses requisitos
não faz parte desta configuração. Instale as dependências Python no virtualenv:

```sh
cd Backend
.venv/bin/python -m pip install -r requirements-dev.txt
```

Em um terminal, dentro de Backend:

```sh
firebase emulators:start --only firestore --project demo-dominando-animacao-test --config firebase.json
```

Projeto demo fixo, sem recursos Firebase reais. Não é necessário .firebaserc.
O CLI pode baixar o binário do Emulator na primeira execução.

Suíte unitária normal, sem Emulator:

```sh
.venv/bin/python -m pytest -q
```

Somente testes Emulator, em outro terminal dentro de Backend:

```sh
FIRESTORE_EMULATOR_HOST=127.0.0.1:8080 FIRESTORE_TEST_PROJECT_ID=demo-dominando-animacao-test .venv/bin/python -m pytest --run-firestore-emulator -m firestore_emulator -q
```

Suíte completa com Emulator:

```sh
FIRESTORE_EMULATOR_HOST=127.0.0.1:8080 FIRESTORE_TEST_PROJECT_ID=demo-dominando-animacao-test .venv/bin/python -m pytest --run-firestore-emulator -q
```

Sem opt-in, integrações são deselecionadas. Com opt-in, configuração ausente,
inválida ou Emulator inacessível causa falha antes de cliente/write.
Somente 127.0.0.1:8080 e o projeto exato são aceitos. Cleanup usa o endpoint REST
exclusivo do Emulator, sem proxy, antes/depois de cada teste, com os mesmos guards.
Isso apaga apenas a base default desse projeto demo no Emulator.
Não execute duas suítes simultâneas ou pytest-xdist: o cleanup é global para essa
base isolada. Os testes usam dados sintéticos e nenhuma coleção comercial.

Os testes antigos continuam usando seus mocks. Para futura integração com o
repositório, injete explicitamente este cliente em mocks test-only; não chame a
inicialização de produção. Contenção/concorrência comercial ficam fora desta etapa.
