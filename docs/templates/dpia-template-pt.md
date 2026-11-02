<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Avaliação de impacto sobre a proteção de dados (AIPD): [NOME DO CAMPO OU CLUBE]

> **MODELO para a organização de um campo adotar e adaptar. Não é
> aconselhamento jurídico.** Uma AIPD (RGPD, art. 35.º) é um dever do
> **responsável pelo tratamento**: o projeto Atalaia não a pode fazer por um
> campo. Este modelo cobre as três operações de tratamento do Atalaia que a
> exigem, escritas a partir do que o software faz hoje e das posições que o
> advogado do responsável pelo projeto aprovou em 2026-10-30. Versão em
> inglês: `dpia-template.md`; dizem o mesmo.
>
> Como ler as marcas:
> - **[PARÊNTESES RETOS]**: o que o campo preenche.
> - **[ESCOLHA DO CAMPO: ...]**: uma escolha que cabe à organização do campo.
> - Confirme cada afirmação com o que o campo realmente faz, apague o que
>   não se aplica (por exemplo a partilha, se o campo nunca a ligar), apague
>   todas as marcas, e date e assine (secção 9).
>
> Leia-o com `privacy-notice-pt.md` (o aviso diz o que se diz às pessoas;
> este documento diz porque o tratamento se justifica e como se mantêm
> pequenos os seus riscos) e com `dpa-template.md` (modo alojado).
>
> Versão: [draft-2026-10-30]

## 1. Porquê uma AIPD

Face aos critérios do CEPD (WP248 rev.01), cada uma das três operações abaixo
cumpre pelo menos dois critérios, pelo que é precisa uma AIPD (art. 35.º,
n.º 1):

| Operação | Critérios cumpridos |
| --- | --- |
| Registo de infrações e banimentos (3) | Avaliação de pessoas (o indicador de reincidente); dados usados para decidir o acesso a um serviço (um banimento); possivelmente pessoas vulneráveis (menores a jogar) |
| Partilha de leituras de cronógrafo entre campos (4) | Cruzamento de dados de responsáveis diferentes; dados usados para decidir o acesso a um serviço; possivelmente menores |
| Posições em direto durante um jogo (5) | Controlo sistemático da localização; possivelmente menores |

O campo deve também confirmar a lista da CNPD dos tratamentos que exigem uma
AIPD (Regulamento n.º 1/2018). [ESCOLHA DO CAMPO: registar aqui o
resultado.]

## 2. O campo e o sistema

- **Responsável pelo tratamento:** [NOME LEGAL, MORADA, NIF DA ORGANIZAÇÃO];
  contacto [EMAIL].
- **Encarregado de proteção de dados:** nenhum nomeado: o campo não é um
  organismo público e as suas atividades principais não são o controlo
  regular e sistemático de pessoas em grande escala nem o tratamento em
  grande escala de categorias especiais de dados (art. 37.º, n.º 1).
  [ESCOLHA DO CAMPO: alterar se nomear um.]
- **Onde estão os dados:** o controlador do jogo do campo (um Raspberry Pi
  ou um telemóvel, sem internet); os telemóveis de quem joga; opcionalmente
  um servidor, gerido pelo campo ou alojado por um subcontratante, o
  operador do hub, **num centro de dados na UE**.
- **Quem vê os dados:** a equipa do campo (administração, organização,
  marshals) conforme o papel; cada pessoa vê os seus dados.
- **O projeto** escreve o software e não recebe nenhum dado do campo.
- **Aviso:** o aviso de privacidade do campo, versão [VERSÃO], é mostrado ao
  registar e no check-in.
- **Número de pessoas:** cerca de [NÚMERO] por ano; [ESCOLHA DO CAMPO: se
  participam menores de 18 anos e a regra do próprio campo para eles].

## 3. Registo de infrações e banimentos

### 3.1 Descrição

- Um marshal mede uma réplica com um cronógrafo. **A leitura é assinada**
  pela chave do marshal, pelo que não pode ser alterada depois sem ser
  detetado.
- Uma leitura acima do limite do campo (ou dentro da tolerância) cria uma
  **infração**. O software marca a pessoa como **"reincidente"** quando tem
  uma infração anterior no campo cujo desfecho foi mais do que um simples
  aviso; **os simples avisos não contam**. A marca é **indicativa** e di-lo
  nos ecrãs da equipa.
- A equipa pode registar um **desfecho**: `aviso`, `retirada` (réplica não
  permitida) ou `banimento`. **O software não aplica nenhum**: nada bloqueia
  o check-in, a inscrição ou o início de sessão por causa de um desfecho.
  Uma pessoa decide e fica registada em cada um.
- Um `banimento` tem uma **data de fim**: 12 meses por omissão, nunca mais do
  que o campo guarda as leituras de cronógrafo. O campo informa a pessoa.
- As infrações e os desfechos **nunca saem do campo** que os registou.
- A pessoa vê as suas leituras na conta ou na app. As leituras são apagadas
  depois do prazo do campo (365 dias por omissão).
- Os limites do campo são regras do próprio campo; não são verificados face
  a nenhuma lei.

### 3.2 Fundamento

- **Art. 6.º, n.º 1, alínea f), interesses legítimos**, avaliados na secção
  6.
- **Não são dados do art. 10.º.** Uma infração é a violação das regras de um
  campo privado, não um crime; o campo não apura nenhuma infração penal e os
  limites são seus.
- **Nenhuma decisão exclusivamente automatizada (art. 22.º).** A marca de
  reincidente é um indicador para a equipa; cada desfecho é fixado por uma
  pessoa.

### 3.3 Necessidade e proporcionalidade

- O mínimo de dados: o identificador de jogador por campo, a réplica e a
  leitura assinada; nada de nome, data de nascimento, fotografia ou
  documento de identificação.
- O desfecho fica no campo; só as leituras podem ir para outros campos
  (secção 4), e só com consentimento.
- Os banimentos acabam; a marca de reincidente ignora os simples avisos; a
  conservação é limitada e aplicada por uma limpeza diária.

## 4. Partilha de leituras de cronógrafo entre campos (opcional)

### 4.1 Descrição

- Desligada por omissão. Um campo liga-a; quem tem contas em dois campos
  liga-as com um código de uso único e dá **consentimento por campo**.
- O hub guarda então, em tabelas comuns, uma cópia **só das leituras
  assinadas** (não das infrações, não dos desfechos, não dos nomes) de cada
  campo em que a pessoa consentiu, e a equipa do outro campo pode lê-las.
  Retirar o consentimento, desligar as contas ou apagar a conta remove a
  cópia.
- Finalidade: segurança das réplicas. Um campo pode ver que uma réplica
  mediu acima do limite noutro sítio antes de a deixar entrar no seu. A
  equipa mede ela própria a réplica antes de decidir seja o que for.

### 4.2 Papéis (art. 26.º e 28.º)

- Cada campo é o **responsável pelo tratamento** dos dados de quem joga nele.
- O operador do hub é **subcontratante** de cada campo (art. 28.º), ao abrigo
  do acordo de subcontratação, e trata as tabelas partilhadas como
  subcontratante dos campos em conjunto.
- **Só no passo da partilha, os campos participantes são responsáveis
  conjuntos** (art. 26.º). O acordo é um conjunto-tipo de termos de partilha
  que cada campo aceita no software ao ligar a partilha (aceitação, versão e
  data registadas). O essencial, que o aviso de cada campo repete (secção
  2.4): âmbito só as leituras assinadas de quem consentiu nos dois campos;
  finalidade a segurança das réplicas, nunca marketing, pontuar pessoas nem
  recusar a entrada só com base nas leituras de outro campo; a pessoa pode
  dirigir-se a **qualquer** campo participante, que trata o pedido ou o
  reencaminha em 7 dias; um campo que detete uma violação avisa os outros e o
  operador do hub em 48 horas, e cada um notifica a autoridade quanto aos
  seus dados; um campo que desligue a partilha deixa de ler e as cópias que
  publicou são apagadas.
- **Fundamento quanto aos dados da pessoa:** art. 6.º, n.º 1, alínea a), o
  consentimento, por campo, revogável a qualquer momento.

### 4.3 Necessidade e proporcionalidade

- Só as leituras assinadas passam; consentimento por campo; nenhum efeito no
  acesso da pessoa a não ser pela medição da própria equipa.
- O alojamento é só na UE; os subcontratantes do hub constam do anexo do
  acordo de subcontratação.

## 5. Posições em direto durante um jogo

### 5.1 Descrição

- Uma opção à parte **no check-in, nunca vem já marcada**, jogo a jogo.
  Recusar nunca bloqueia o check-in nem o jogo (art. 7.º, n.º 4); a pessoa
  pode parar a qualquer momento.
- Enquanto partilha e um jogo decorre, o telemóvel envia a última posição GPS
  ou qual das balizas Bluetooth do campo ouve melhor. O controlador guarda
  **só a última posição de cada jogador, para esse jogo, e apaga-a quando o
  jogo termina**. Não guarda trajeto.
- Quem a vê: a própria pessoa; o seu squad ou a sua equipa, conforme o modo
  de jogo permitir; os marshals e a organização; uma organização remota
  **só quando o campo a liga** (só em memória, nada guardado); dispositivos
  ATAK da equipa, se o campo usa ATAK. Nunca pelo rádio, por MQTT, para
  outros campos, para o marcador, num evento, num registo nem na base de
  dados do servidor.

### 5.2 Fundamento

Art. 6.º, n.º 1, alínea a), consentimento, como acima. Deixar a equipa ver as
posições serve a finalidade consentida: a segurança e a gestão do jogo.

### 5.3 Necessidade e proporcionalidade

- Opcional; o jogo joga-se por inteiro sem ela.
- Só a última posição, apagada no fim do jogo; uma sala, não um metro, onde
  há balizas.
- Os reencaminhamentos remoto e ATAK estão desligados por omissão e não
  guardam nada.

## 6. Avaliação do interesse legítimo (registo de infrações e banimentos)

| Passo | Avaliação |
| --- | --- |
| Interesse | A segurança física de todas as pessoas no campo; fazer cumprir as regras de segurança do próprio campo; poder mostrar, se houver uma lesão, que as réplicas foram verificadas. |
| Necessidade | Um registo assinado de quem trouxe que réplica e com que potência é o mínimo de dados que deixa a equipa agir perante incumprimentos repetidos; nenhum nome, só o identificador por campo e a réplica. Sem histórico, quem é afastado num dia pode voltar no seguinte com a mesma réplica. |
| Ponderação | Os dados limitam-se ao campo (desfechos) ou a campos em que a pessoa consentiu (leituras); guardam-se durante o prazo de conservação; só a equipa e a pessoa os veem; não há perfis para além do único indicador informativo; nenhuma consequência automática; os banimentos acabam; a pessoa pode ver, contestar e opor-se. Expectativa razoável: quem joga em campos de airsoft espera verificações de cronógrafo e sanções para réplicas acima do limite. |
| Resultado | O interesse não é afastado, **desde que** as salvaguardas estejam em vigor: uma data de fim para os banimentos, uma via de contestação, a indicação de que é indicativo, os simples avisos não contarem e uma conservação limitada. |

[ESCOLHA DO CAMPO: acrescentar o que for próprio do campo, por exemplo quem
tem menos de 18 anos.]

## 7. Riscos para as pessoas e as medidas

Classifique cada risco antes e depois das medidas (baixo, médio, alto).
[ESCOLHA DO CAMPO: classificar para o campo.]

| Risco | Operação | Medidas | Antes | Depois |
| --- | --- | --- | --- | --- |
| Uma pessoa é impedida de jogar com base num registo errado ou desatualizado | 3, 4 | Leituras assinadas; a equipa mede ela própria a réplica; desfechos fixados por uma pessoa e registados; os banimentos acabam; contestação pelo contacto; a marca de reincidente é indicativa e ignora os simples avisos | [ ] | [ ] |
| O registo é guardado demais ou usado para outra coisa | 3 | Conservação aplicada por uma limpeza diária; os banimentos nunca duram mais do que as leituras; finalidade limitada no aviso e, na partilha, nos termos de partilha | [ ] | [ ] |
| As leituras de uma pessoa chegam a um campo que ela não escolheu | 4 | Consentimento por campo; ligação por código de uso único feita pela pessoa; a cópia é apagada ao retirar, desligar ou apagar; só passam leituras assinadas | [ ] | [ ] |
| A pessoa não sabe a quem se dirigir | 4 | A secção 2.4 do aviso dá o essencial dos termos; qualquer campo participante trata o pedido ou reencaminha-o em 7 dias | [ ] | [ ] |
| A localização é usada para seguir ou expor alguém | 5 | Opção no check-in; só a última posição, apagada no fim do jogo; acesso da equipa listado; reencaminhamentos remotos desligados por omissão e sem guardar nada; nunca pelo rádio, MQTT nem para o marcador | [ ] | [ ] |
| Quem joga sente-se pressionado a partilhar a posição | 5 | Opção à parte, não marcada; recusar não bloqueia nada; equipa instruída a não pedir que partilhem [ESCOLHA DO CAMPO] | [ ] | [ ] |
| Fuga de dados de um telemóvel, do controlador ou do servidor | todas | HTTPS em tudo; dados do campo separados por segurança ao nível da linha; papéis da equipa exigem início de sessão em dois passos; segredos selados no dispositivo; cópias de segurança do servidor alojado durante [PRAZO]; rotina de violações (secção 8) | [ ] | [ ] |
| Uma pessoa mais nova é tratada sem a palavra de quem exerce as responsabilidades parentais | 3, 4, 5 | Contas a partir dos 16 anos, confirmadas por uma caixa de seleção; quem for mais novo joga pelo check-in sem conta, com as regras parentais do próprio campo [ESCOLHA DO CAMPO] | [ ] | [ ] |
| Dados saem da UE/EEE | alojado | Só centros de dados na UE; qualquer CDN ao abrigo do Quadro de Privacidade de Dados UE-EUA ou de cláusulas-tipo; os fornecedores de início de sessão são escolhidos pela pessoa; a obtenção de mapas pode ser desligada | [ ] | [ ] |

## 8. Violações de dados

O campo informa a CNPD em 72 horas quando uma violação põe as pessoas em
risco e as pessoas sem demora injustificada quando o risco é elevado (art.
33.º e 34.º). Num servidor alojado, o operador do hub informa o campo em 48
horas. Quanto às leituras partilhadas, o campo que detete uma violação avisa
os outros campos e o operador do hub em 48 horas. [ESCOLHA DO CAMPO: quem faz
isto no campo.]

## 9. Consulta, decisão e revisão

- **Opinião das pessoas em causa** (art. 35.º, n.º 9): [ESCOLHA DO CAMPO: por
  exemplo perguntada numa reunião de quem joga; ou porque não é
  apropriado].
- **Encarregado de proteção de dados:** nenhum (secção 2).
- **Consulta prévia da CNPD (art. 36.º):** só é precisa se um risco continuar
  **elevado** depois das medidas. [ESCOLHA DO CAMPO: sim / não, porquê.]
- **Decisão:** [APROVADA / APROVADA COM CONDIÇÕES / NÃO APROVADA], por
  [NOME, FUNÇÃO], em [DATA].
- **Revisão:** quando o software ou as regras do campo mudarem (nova versão
  do aviso, partilha ligada, organização remota ou ATAK ligados, novo prazo
  de conservação) e pelo menos de [12] em [12] meses. Próxima revisão:
  [DATA].
