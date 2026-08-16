# Alterações do módulo Benchmark de Mercado

## 1. Resumo

Foi adicionado ao **NBA Analytics Lab** um módulo de comparação retrospectiva entre as probabilidades produzidas pelo modelo e uma referência probabilística histórica.

O objetivo é avaliar a qualidade estatística do modelo, identificar divergências, medir calibração e encontrar pontos que precisam ser melhorados.

O módulo possui finalidade educacional e analítica. Ele:

- utiliza somente partidas concluídas;
- não consulta informações em tempo real;
- não apresenta recomendações de aposta;
- não trabalha com valores financeiros;
- não classifica partidas como oportunidades;
- não oferece integração com casas ou plataformas de apostas.

## 2. Funcionalidades adicionadas

### 2.1 Nova página no Streamlit

Foi criada a página:

```text
pages/3_Benchmark_Mercado.py
```

Ela aparece automaticamente no menu lateral do Streamlit e contém:

- aviso permanente sobre a finalidade retrospectiva;
- seleção da fonte de dados;
- filtros por temporada;
- filtros por time;
- filtros por data inicial e final;
- cartões com métricas;
- gráfico de comparação das probabilidades;
- gráfico de calibração;
- distribuição dos erros;
- tabela das maiores divergências;
- seção explicando a metodologia.

### 2.2 Base demonstrativa

O módulo inicia com uma base sintética para permitir que a tela seja testada sem depender de dados externos.

O processo demonstrativo:

1. gera partidas sintéticas;
2. ordena as partidas por data;
3. usa os primeiros 80% para treinamento;
4. utiliza os 20% finais para avaliação;
5. produz probabilidades do modelo;
6. cria uma referência sintética separada;
7. calcula as métricas no período de avaliação.

Essa separação temporal reduz o risco de o modelo aprender informações das partidas utilizadas na avaliação.

### 2.3 Importação de CSV histórico

Também foi adicionada a possibilidade de importar um arquivo CSV contendo partidas concluídas.

Colunas obrigatórias:

```text
game_date
home_team
away_team
model_probability
market_probability
home_win
```

Descrição:

| Coluna | Conteúdo |
|---|---|
| `game_date` | Data da partida concluída |
| `home_team` | Time mandante |
| `away_team` | Time visitante |
| `model_probability` | Probabilidade histórica produzida pelo modelo |
| `market_probability` | Referência probabilística histórica |
| `home_win` | `1` se o mandante venceu e `0` se perdeu |

As probabilidades devem estar entre `0` e `1`.

## 3. Validações implementadas

O sistema valida automaticamente:

- presença de todas as colunas obrigatórias;
- formato válido das datas;
- ausência de valores vazios;
- probabilidades entre `0` e `1`;
- resultado contendo somente `0` ou `1`;
- partidas com datas anteriores ou iguais à data atual;
- existência de partidas após a aplicação dos filtros.

Arquivos com partidas futuras são rejeitados, pois o módulo foi projetado exclusivamente para avaliação retrospectiva.

## 4. Métricas adicionadas

### 4.1 Brier Score

Mede o erro quadrático das probabilidades.

- quanto menor, melhor;
- avalia a distância entre a probabilidade prevista e o resultado real;
- permite comparar o modelo com a referência histórica.

### 4.2 Log Loss

Avalia a qualidade das probabilidades e aplica penalidade maior quando uma previsão muito confiante está incorreta.

- quanto menor, melhor;
- ajuda a detectar excesso de confiança.

### 4.3 Acurácia

Mede a proporção de classificações corretas usando o limite de 50%.

A acurácia é apresentada como uma métrica complementar e não deve ser usada sozinha para avaliar probabilidades.

### 4.4 Erro esperado de calibração

Compara a probabilidade prevista com a frequência observada.

Exemplo: em uma amostra grande, previsões próximas de 60% deveriam ocorrer aproximadamente 60% das vezes.

### 4.5 Divergência média

Mede a diferença absoluta entre a estimativa do modelo e a referência histórica.

Níveis utilizados:

| Nível | Diferença absoluta |
|---|---:|
| Baixa | Menor que 5 pontos percentuais |
| Moderada | De 5 a menos de 12 pontos percentuais |
| Alta | 12 pontos percentuais ou mais |

Uma divergência alta significa somente que as estimativas foram diferentes. Ela não representa uma recomendação.

## 5. Visualizações adicionadas

### Comparação de probabilidades

Gráfico de dispersão que mostra:

- referência histórica no eixo horizontal;
- probabilidade do modelo no eixo vertical;
- resultado real da partida por cor;
- linha diagonal representando estimativas iguais.

### Curva de calibração

Compara:

- probabilidade média prevista;
- frequência de vitórias observada;
- modelo;
- referência histórica;
- quantidade de partidas em cada faixa.

Quanto mais próxima uma série estiver da linha diagonal, melhor tende a ser sua calibração.

### Distribuição dos erros

Apresenta a distribuição do erro absoluto do modelo e da referência histórica.

### Tabela de divergências

Mostra as maiores diferenças do período selecionado com:

- data;
- partida;
- probabilidade do modelo;
- probabilidade da referência;
- diferença absoluta;
- nível de divergência;
- resultado final.

## 6. Arquivos criados

```text
src/market_benchmark.py
pages/3_Benchmark_Mercado.py
tests/test_market_benchmark.py
tests/test_market_benchmark_page.py
docs/benchmark_mercado.md
docs/alteracoes_benchmark_mercado.md
```

### Responsabilidades

| Arquivo | Responsabilidade |
|---|---|
| `src/market_benchmark.py` | Validação, geração demonstrativa, cálculos e tabelas de calibração |
| `pages/3_Benchmark_Mercado.py` | Interface, filtros, cartões, gráficos e explicações |
| `tests/test_market_benchmark.py` | Testes das regras e métricas |
| `tests/test_market_benchmark_page.py` | Teste de carregamento da página Streamlit |
| `docs/benchmark_mercado.md` | Documentação da metodologia |
| `docs/alteracoes_benchmark_mercado.md` | Registro consolidado das mudanças |

## 7. Arquivo atualizado

O arquivo `README.md` foi atualizado com:

- descrição do benchmark retrospectivo;
- novas funcionalidades;
- nova estrutura de arquivos;
- formato esperado do CSV;
- referência para a documentação completa;
- esclarecimento de que o projeto não apresenta recomendações.

## 8. Testes adicionados

Foram criados testes para verificar:

- estrutura da base demonstrativa;
- limites das probabilidades;
- resultados válidos;
- cálculo das métricas;
- criação da tabela de calibração;
- rejeição de partidas futuras;
- rejeição de probabilidades inválidas;
- carregamento da página no Streamlit.

Resultado da validação completa:

```text
21 testes passaram
```

## 9. Como executar

No terminal, dentro da pasta `nba-analytics`:

```powershell
streamlit run app.py
```

Depois, abra a opção **Benchmark de Mercado** no menu lateral.

Para executar os testes:

```powershell
pytest -q
```

## 10. Próximas melhorias seguras

- salvar versões históricas das previsões do próprio modelo;
- comparar diferentes versões do modelo;
- adicionar segmentação por mês e fase da temporada;
- calcular métricas por time;
- exibir tamanho da amostra em todas as visualizações;
- adicionar intervalos de confiança nas curvas de calibração;
- permitir exportar relatórios estatísticos;
- criar histórico de desempenho após cada retreinamento.
