# Jev: contexto e perguntas

Referências oficiais consultadas em 18/09/2026. Orientações próprias para este
plugin; limites do provedor devem ser conferidos ao atualizar o modelo.

## Montagem do contexto

`state` contém os fatos usados em todas as perguntas da chamada. Pode ser texto,
objeto ou array. O servidor remoto conhece apenas o conteúdo enviado: um caminho
de arquivo ou URL não equivale ao conteúdo da evidência.
[State](https://docs.typesafe.ai/concepts/state)

Monte o contexto da decisão com objetivo, regras aplicáveis, artefato avaliado,
evidências identificadas, alternativas e lacunas. Registre origem e revisão quando
disponíveis; separe fatos observados de inferências. Ao retomar, confira alterações
nas fontes antes de reutilizar um julgamento.

Política aprovada para o plugin: busque evidências para resolver as lacunas por
até três rodadas. Se uma rodada não trouxer informação nova, ou se a lacuna
persistir após a terceira, encaminhe para revisão humana com a pergunta concreta,
as evidências reunidas e o que ainda falta. Se o contexto ficar suficiente antes,
prossiga para a avaliação conforme a política dos gates.

Busque cobertura das evidências necessárias. Conteúdo irrelevante pode piorar o
resultado; indireções e cálculos também são limitações documentadas. Resolva
relações importantes explicitamente e faça cálculos determinísticos em Python.
Se o estado exceder o orçamento do provedor, divida por decisão ou recupere trechos
específicos; mantenha omissões visíveis, sem truncamento silencioso.
[Como construir](https://docs.typesafe.ai/concepts/how-to-build-with-system-one),
[Limitações do Jev 1.13](https://docs.typesafe.ai/model-jaggedness/jev-1.13)

## Formulação das perguntas

IDs correlacionam entradas e saídas; não substituem instruções. Escreva a pergunta
completa e aponte para campos explícitos de `state`. Descreva o significado de cada
opção e inclua ausência de evidência ou de candidato adequado quando possível.
Valide duplicatas antes de converter listas em dicionários.
[Primitives](https://docs.typesafe.ai/primitives)

Perguntas do mesmo request são independentes. Agrupe as que usam o mesmo estado;
se a próxima pergunta depende da resposta anterior, componha o novo estado em
Python e faça outra chamada. Não peça ao modelo para ler uma resposta ainda não
produzida dentro do próprio lote.
[Parallel questions](https://docs.typesafe.ai/cookbooks/parallel_questions)

Estruturas JSON podem esclarecer fronteiras entre categorias e organizar rubricas
na API direta TypeSafe. O OpenRouter tem schema próprio: não presuma que aceita
todos os formatos de `instructions` e `criteria` do SDK TypeSafe. Os exemplos
validados neste projeto usam instruções e descrições textuais.
[Advanced structure](https://docs.typesafe.ai/primitives/advanced)

## Exemplo de ausência de evidência

Para o critério “todos os testes exigidos passaram”, envie o resultado observado
da suíte. Ofereça `satisfied`, `not_satisfied` e `insufficient_context`, descrevendo
cada opção. “A alteração foi implementada” não demonstra execução de testes.
Se faltar o resultado, obtenha-o antes de permitir que esse gate aprove a mudança.

Na chamada real do projeto, a ausência dos resultados produziu
`insufficient_context` com `confidence=1`. A confiança estava no diagnóstico de
falta de evidência, não na aprovação da alteração.
