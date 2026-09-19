# Cliente público Dev Decision

O bootstrap está em `launcher/`, com o nome `@felipeoff/dev-decision` e licença
MIT. Ele aceita macOS/Linux, exige Python 3.12+ e instala a mesma versão do
package `dev-decision-client` em um venv dedicado. Node termina após iniciar
o cliente Python.

O entry point Python `dev_decision.public_cli` oferece `install`, `update`,
`doctor`, `smoke` e `uninstall`. O setup detecta Codex, Claude Code, Cursor,
Grok Build e Grok Bot, mostra um toggle por harness presente, solicita host e
API key sem eco e usa o profile `default`. `--harness` seleciona integrações
explícitas; `--yes` instala todas as detectadas. Não forneça API keys na linha
de comando. A variável `DEV_DECISION_MCP_API_KEY` pode ser usada em automações
locais; seu valor vai apenas ao arquivo de credenciais `0600`.

Cada wrapper em `~/.local/bin/dev-decision-<harness>` lê essa credencial e a
injeta só no processo correspondente. O profile guarda endpoint, harnesses
habilitados e a referência da credencial; a entrada MCP nativa guarda a
referência à variável de ambiente. Os binários originais dos harnesses
continuam disponíveis.

Instalação repetida preserva configurações e skills não gerenciadas. `update` é
sempre explícito: cria um venv novo, conserva o anterior como backup e restaura
runtime, estado e skills se a atualização local falhar. Não existe auto-update.
Falha no setup restaura os destinos gerenciados da transação, inclusive quando
um harness posterior falha depois de outro já ter sido escrito. Uninstall
remove somente artefatos inalterados do plugin.

Doctor verifica integridade da skill, runtime, initialize e skills/list do
app-server, autenticação MCP, handshake SemVer/capabilities e catálogo de
tools. Também informa o modo e o limite validado de Codex, Claude Code, Cursor,
Grok Build e Grok Bot. Não inicia `turn/start`, não consome inferência e não afirma ter testado
uma pergunta nativa do modelo. Esse roundtrip permanece nos testes com double.

## Release e verificação

`scripts/export_public_release.py DESTINO` cria uma árvore nova somente com os
clientes, schemas, launcher, skills e documentação permitidos. O export não leva
histórico Git, servidor, banco, adapters privados, logs ou credenciais. O arquivo
`release-manifest.json` registra o commit de origem e o SHA-256 de cada arquivo.

As versões de `pyproject.toml` e `launcher/package.json` precisam ser idênticas.
O workflow público publica npm com `--provenance` e Python por trusted publishing,
além de gerar `SHA256SUMS`. Verifique provenance no registry e compare os hashes
baixados antes de instalar.

```sh
npx @felipeoff/dev-decision@0.1.0 install
npx @felipeoff/dev-decision@0.1.0 doctor --project .
npx @felipeoff/dev-decision@0.1.0 update
npx @felipeoff/dev-decision@0.1.0 uninstall
```

Sem MCP, os harnesses continuam disponíveis e mantêm a decisão para revisão
humana. Diferença de major do protocolo também volta ao harness. Codex usa
app-server controlado; Claude Code usa hooks; Cursor e Grok Build usam ACP
controlado; Grok Bot exige skill e Custom MCP manuais e não oferece interceptação
obrigatória por contrato público.

## Limites

O tracker autorizado neste ciclo é GitHub Issues. GitLab, Jira, Beads e
documentos locais permanecem escolhas de projeto na spec; este cliente publica
somente referências `github.com` até existirem adapters equivalentes.

O export prepara o repositório público com histórico novo; a publicação nos
registries continua sendo uma ação manual do mantenedor. Nunca publique o wheel
deste repositório privado: ele contém o servidor.

O setup global instala as skills de workflow e o adapter de cada harness
escolhido. Codex usa app-server controlado; Claude Code usa hooks nativos;
Cursor e Grok Build usam ACP controlado; Grok Bot permanece cooperativo, com
skill e Custom MCP manuais, e não oferece interceptação obrigatória. O wrapper
injeta a credencial no processo; o controle de perguntas estruturadas continua
na API Python de cada cliente controlado, sem interceptação universal da
interface nativa.
