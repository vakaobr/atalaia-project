<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Aviso de privacidade: [NOME DO CAMPO OU CLUBE] (app Atalaia, controlador do campo e servidor do campo)

> **RASCUNHO. Não é aconselhamento jurídico. Ainda não foi revisto por um
> advogado.** Este é o primeiro rascunho completo, escrito pelo projeto
> Atalaia a partir do que o software faz hoje (2026-10-28). O responsável
> pelo projeto vai pedir a revisão a um advogado que conheça o RGPD e a Lei
> n.º 58/2019 **antes** de qualquer campo o usar, e antes de qualquer
> serviço alojado entrar em funcionamento (decisão P4-6). Nada aqui é uma
> promessa do projeto a ninguém: é um texto para a organização do campo
> verificar, preencher e adotar como seu.
>
> **Estado em 2026-10-30.** O advogado do responsável pelo projeto aprovou
> as posições jurídicas que este modelo passa a afirmar: os fundamentos, a
> verificação do cartão de filiação, a idade mínima, as transferências, as
> regras de contitularidade da partilha, como acabam e se contestam os
> banimentos. O responsável pelo projeto decidiu o encarregado de proteção de
> dados, os dados de posição e a conservação do histórico de jogos. As marcas
> que restam são os pontos ainda em aberto, listados na Parte D. Continua a
> ser um **modelo**: cada campo preenche os seus dados, confirma cada
> afirmação com o que realmente faz e adota o texto como seu. Cada campo faz
> também a sua avaliação de impacto (art. 35.º), para a qual
> `dpia-template-pt.md` é o ponto de partida.
>
> Como ler as marcas:
> - **[PARÊNTESES RETOS]**: o que o campo preenche (um nome, uma morada).
> - **[ESCOLHA DO CAMPO: ...]**: uma escolha que cabe à organização do campo
>   (um prazo, uma regra, se uma funcionalidade é usada).
> - **[ADVOGADO: ...]**: uma escolha jurídica que o código não pode fazer (um
>   fundamento, uma redação, um dever). Quando o rascunho propõe uma
>   resposta, di-lo. Só os pontos ainda em aberto (Parte D) levam esta marca.
> - Antes de usar, apague o que não se aplica ao campo e apague todas as
>   marcas.
>
> O português europeu e o inglês acompanham-se: `privacy-notice-en.md` diz o
> mesmo. Quando alterar o aviso, suba a versão que o servidor guarda com cada
> consentimento (`ATALAIA_PRIVACY_NOTICE_VERSION`) e a `notice_version` do
> check-in no controlador do campo. O servidor publica o aviso que o campo
> adotou (um ficheiro por língua e versão, em `ATALAIA_PRIVACY_NOTICE_DIR`:
> `server/privacy-notice/README.md`) e pede às contas que consintam de novo
> quando a versão muda; o texto continua a ser do campo.
>
> Versão: [draft-2026-10-30]

Este ficheiro tem três partes:

- **Parte A**, o aviso de privacidade completo do campo (secções 1 a 14);
- **Parte B**, a versão curta mostrada na app quando alguém cria uma conta
  (a decisão S17-16 espera por ela);
- **Parte C**, o aviso curto para o cartaz de check-in e para a página de
  check-in do controlador do campo.

No fim, a **Parte D** lista os pontos que se pede ao advogado que decida.

---

# Parte A. O aviso completo

## 1. Quem é responsável pelos teus dados

O responsável pelo tratamento é **[NOME LEGAL DA ORGANIZAÇÃO]**, [MORADA],
[NIF], que organiza os jogos no [NOME DO CAMPO] (o "campo"). Contacto para
tudo o que diga respeito aos teus dados: [EMAIL OU MORADA].

Não nomeámos um encarregado de proteção de dados: [o campo] não é um
organismo público e as suas atividades principais não consistem no
controlo regular e sistemático de pessoas em grande escala nem no
tratamento em grande escala de categorias especiais de dados (RGPD, art.
37.º, n.º 1). [ESCOLHA DO CAMPO: se o campo nomear um, diga-se aqui, com o
nome e o contacto.]

O Atalaia é software livre feito pelo projeto Atalaia. **O projeto não
recebe nem vê os dados deste campo.** Corre no equipamento do próprio campo
(ou num servidor que o campo escolheu). O projeto não é responsável pelo
tratamento dos teus dados aqui.

**Papéis.** O campo é o **responsável pelo tratamento** dos dados de quem
joga. Um operador de hub, se existir, é o seu **subcontratante** (abaixo).
Quando vários campos do mesmo hub ligam a partilha de leituras de cronógrafo
(2.4), esses campos são **responsáveis conjuntos só nesse passo da
partilha** (art. 26.º); o essencial do seu acordo está em 2.4.

### Como o campo usa o Atalaia

Conforme o que o campo usa, os teus dados estão num, dois ou três sítios. O
resto deste aviso diz que dados estão onde.

1. **O controlador do jogo do campo**, um Raspberry Pi ou um telemóvel no
   campo, que gere o jogo, o check-in e o cronógrafo. Funciona **sem
   internet**. Tudo o que dás no check-in fica aqui.
2. **O teu telemóvel**, com a app Atalaia (armazenamento descrito na secção
   9).
3. **Um servidor do campo** (opcional), onde se criam contas, se faz a
   inscrição em jogos marcados e onde ficam os resultados e os registos do
   cronógrafo entre jogos. Ou é:
   - gerido pelo próprio campo, ou
   - **[SE FOR ALOJADO:]** alojado para o campo por **[NOME LEGAL E MORADA
     DO SERVIÇO DE ALOJAMENTO]** (o "operador do hub"), que é o
     **subcontratante** do campo: trata os dados apenas segundo as
     instruções do campo, ao abrigo de um acordo de subcontratação (art.
     28.º), e não os usa para nada seu. Cada campo alojado tem o seu próprio
     espaço de base de dados, separado. A conta é por campo: quem joga em
     dois campos alojados tem duas contas, que nada liga.

[ESCOLHA DO CAMPO: dizer quais destes o campo usa. Se o campo não tem
servidor, apague tudo o que está marcado "(servidor)" e a secção 4.2.]

## 2. O que guardamos, para quê e com que fundamento

O fundamento é um dos do art. 6.º, n.º 1, do RGPD: a) o teu consentimento,
b) um contrato contigo, c) uma obrigação legal, f) os nossos interesses
legítimos. As tabelas abaixo dizem qual se aplica a cada finalidade. Onde o
software regista um consentimento (a partilha de cronógrafo, a partilha da
tua posição, o uso do nome do teu fornecedor), diz-se.

**Uma conta assenta em contrato (art. 6.º, n.º 1, alínea b)):** é o serviço
que pedes (inscrever-te em jogos, ver o teu histórico). Criá-la não pede
consentimento. O software regista que versão deste aviso te foi mostrada ao
registares-te. O consentimento (alínea a)) fica para as coisas opcionais
acima, cada uma separada, granular e revogável.

### 2.1 Conta e início de sessão (servidor)

| Dados | Para quê | Fundamento |
| --- | --- | --- |
| Nome de utilizador, email opcional, quando a conta foi criada e usada pela última vez | Dar-te uma conta | b) contrato: o serviço que pedes. O software regista a **versão do aviso mostrada** ao registares-te |
| **Palavra-passe**: apenas um hash Argon2id, nunca a palavra-passe. A palavra-passe é opcional | Iniciar sessão com palavra-passe | b) contrato |
| **App de autenticação (TOTP)**: se está ativa e o segredo, guardado cifrado. Obrigatória para quem é marshal, da organização ou da administração | Um segundo passo no início de sessão; protege as contas da equipa | f) segurança (e art. 32.º); b) contrato |
| **Chaves de acesso** (passkeys, WebAuthn): um nome (teu, ou dado pelo servidor), o nome do anfitrião e as datas. O servidor guarda só a parte pública; **nunca** a chave privada nem o identificador da chave de acesso | Iniciar sessão sem palavra-passe | b) contrato |
| **Início de sessão com Google, Microsoft ou Apple**: **só o nome do fornecedor e o identificador opaco ("subject") que o fornecedor dá para ti, e quando o ligaste**. O servidor não pede email, fotografia nem mais nada ao iniciares sessão. **Uma exceção, só quando carregas em "Usar o meu nome de Google" ou "Usar o meu nome de Microsoft" na página da tua conta**: o fornecedor diz então também o teu nome ao servidor, uma vez, para te sugerir um nome de utilizador. **Esse nome só é lido porque o pediste, é transformado numa sugestão que podes editar e não fica guardado**: só se guarda o nome de utilizador que confirmares. O fornecedor fica a saber em que site estás a entrar, como em qualquer início de sessão social | Iniciar sessão sem palavra-passe | b) contrato, pelo início de sessão. **Ler o teu nome para sugerir um nome de utilizador: a) o teu consentimento**, dado ao carregares no botão |
| Os teus **papéis** no campo (participante, líder de squad, VIP, marshal, organização, espectador, administração) | Deixar-te fazer o que o papel permite | b) contrato; para a equipa também f) |
| Sessões: um hash do token de renovação, o endereço e o navegador ou app de cada início de sessão, as horas | Manter a sessão e a conta seguras | f) segurança do serviço |
| **Registo de segurança**: inícios de sessão, falhados, bloqueios, alterações à conta, papéis atribuídos, com o endereço. Nunca uma palavra-passe nem um código | Segurança e responsabilização | f) |
| **Registos de consentimento**: o que aceitaste, que versão do aviso, quando | Provar o consentimento (art. 7.º, n.º 1) e que aviso foi mostrado (art. 5.º, n.º 2) | c) obrigação legal (responsabilização) |

### 2.2 Inscrição num jogo e check-in

| Dados | Para quê | Fundamento |
| --- | --- | --- |
| **Inscrição (servidor)**: o teu identificador de jogador no campo, um nome a mostrar no jogo (por omissão o teu nome de utilizador), a preferência de equipa, o teu **número de associado** se o jogo o pedir, as réplicas que declaras, se vieste ou não, se pagaste (o campo anota; nenhum pagamento é processado) | Organizar o jogo | b) contrato: o jogo em que te inscreves |
| Um **bilhete de inscrição**: um segredo aleatório mostrado uma vez; só se guarda um hash | Associar a tua chegada à inscrição | b) contrato |
| **Check-in no campo (controlador)**: o nome ou a alcunha que escreves, a preferência de equipa, as réplicas que declaras, **o resultado da verificação do cartão de associado** se o campo a fizer (2.3; **nada verifica o número com ninguém**), a hora. O teu telemóvel cria um identificador para este campo; o controlador guarda-o e um hash do segredo que o acompanha. **Não se pede email, telefone, data de nascimento, documento de identificação nem fotografia** | Gerir o jogo e saber quem está no campo | b) contrato: o jogo em que entras; f) o interesse do campo em jogos seguros |
| **Filiação numa associação**: ver 2.3 | | |
| Um marshal ou a organização pode confirmar ou fazer o check-in à mão mesmo que a verificação da filiação falhe. Fica registado com o identificador da pessoa e o veredicto, nunca o número | Decisão da equipa | f) |

### 2.3 Filiação numa associação (APD): a verificação do cartão

Alguns campos pedem a filiação numa associação de airsoft (em Portugal,
uma "APD"; noutros países, um clube, uma federação ou uma seguradora). **No
check-in, a equipa verifica o teu cartão de associado.** O software toma a
associação, o número e a data de validade, e diz à equipa "válido",
"caducado", "não aceite" ou "em falta". Nunca verifica o número com a
associação nem com mais ninguém.

**O número é apagado logo que o check-in é confirmado.** O que o campo
guarda, com o check-in, é um **retrato do veredicto**: a associação, a data
de validade, o resultado e quem o verificou, como prova de que a verificação
foi feita (para uma inspeção ou uma seguradora). O número não é mostrado a
quem joga, ao marcador só de leitura nem em nenhum evento, registo ou
mensagem MQTT; a equipa (organização, marshals) vê-o só até o check-in ser
confirmado. O número de uma inscrição no servidor tem o mesmo destino e, em
qualquer caso, é apagado no máximo 30 dias depois do jogo.

**Fundamento.** A filiação numa associação desportiva não é uma categoria
especial de dados (art. 9.º). Em Portugal o campo verifica a filiação porque
as regras da prática do airsoft (Lei n.º 5/2006 e a sua regulamentação) fazem
da filiação numa APD reconhecida uma condição para jogar, pelo que o
fundamento é o **art. 6.º, n.º 1, alínea c), obrigação legal**. Onde não
existe esse dever (fora de Portugal, ou outro tipo de filiação), o
fundamento é a alínea f) (o seguro e as regras do campo) ou b), quando é uma
condição do jogo em que te inscreves.
[ESCOLHA DO CAMPO: se o campo a pede de todo, qual destes fundamentos se
lhe aplica, e se é preciso para jogar ou só para se inscrever.]

### 2.4 Leituras de cronógrafo, réplicas, infrações e banimentos

| Dados | Para quê | Fundamento |
| --- | --- | --- |
| As **réplicas** que declaras ou que o campo regista por ti: tipo, classe, marca e modelo, um identificador num **autocolante NFC ou numa etiqueta QR** (`ATL-` e oito caracteres: nada pessoal na etiqueta em si, mas o registo do campo liga-a a ti) | Segurança: limites de potência das réplicas | f) segurança de quem joga |
| **Leituras de cronógrafo** (a energia de um tiro, a hora, o check-in ou a verificação pontual, o resultado passa, aviso ou falha), **assinadas pelo marshal**; a chave pública do marshal | Segurança | f) interesses legítimos: a segurança de todas as pessoas no campo |
| **Infrações**: uma verificação pontual que falhou ou deu aviso, quanto passou do limite, e se estás marcado como **reincidente**. A equipa regista um desfecho: `aviso`, `retirada` (réplica não permitida) ou `banimento` | Segurança; deixar a equipa ver o histórico antes de decidir | f) interesses legítimos (ver abaixo). **Não** são dados sobre infrações penais (art. 10.º): uma infração é a violação das regras do próprio campo |

**Infrações, banimentos e a marca de "reincidente".**

- **Nada é automático.** O software não aplica nenhum destes desfechos: um
  "banimento" é uma nota para a equipa, e é uma pessoa que decide e fica
  registada em cada desfecho. Nenhuma decisão é tomada exclusivamente por
  meios automatizados (art. 22.º).
- **"Reincidente" é indicativo.** É mostrado à equipa, com a indicação de
  que é indicativo, como um indicador e nunca como uma decisão. Só conta
  infrações anteriores cujo desfecho foi mais do que um simples `aviso`:
  os simples avisos não contam.
- **Um banimento acaba.** Tem uma **data de fim**: 12 meses por omissão,
  **nunca mais do que o campo guarda as leituras de cronógrafo** (secção 7).
  O campo informa-te do desfecho e da data de fim. [ESCOLHA DO CAMPO: um
  prazo por omissão mais curto.]
- **Podes contestar um desfecho** pelo contacto do campo (secção 14).
  Tens também o direito de te opor a este tratamento (art. 21.º).
- **O interesse legítimo** (art. 6.º, n.º 1, alínea f)) é a segurança física
  de todas as pessoas no campo, fazer cumprir as regras de segurança do
  próprio campo e poder mostrar, se houver uma lesão, que as réplicas foram
  verificadas. Precisa de um registo assinado de quem trouxe que réplica e
  com que potência; é o mínimo de dados que deixa a equipa agir perante
  incumprimentos repetidos (o identificador por campo e a réplica, não um
  nome). Os dados ficam no campo, ou só vão para campos em que
  consentiste; guardam-se como na secção 7; só a equipa e tu os veem; não
  há perfis para além do único indicador nem consequência automática. Quem
  joga espera verificações de cronógrafo e sanções para réplicas acima do
  limite. O campo ponderou isto por escrito (a avaliação do interesse
  legítimo em `dpia-template-pt.md`).

| Dados | Para quê | Fundamento |
| --- | --- | --- |
| **Partilha com outros campos** (opcional): se dois campos a ativarem **e consentires em cada um dos dois**, a equipa do outro campo vê as tuas leituras, cada uma com a chave pública do marshal. Os identificadores de cada campo nunca são cruzados: só uma conta que tenha ambos os liga. Num **hub alojado**, onde cada campo tem as suas contas, ligas tu as tuas contas com um código de uso único; o operador do hub guarda então, por cada campo em que consentiste, uma cópia das leituras assinadas desse campo sobre ti nas tabelas de partilha do hub, e só os campos em que consentiste a podem ler. Retirar o consentimento, desligar as contas ou apagar a conta remove essa cópia | Outro campo ver o historial de uma réplica | a) o teu consentimento próprio, por campo, que podes retirar na tua conta |

**Partilha entre campos: quem é responsável (art. 26.º).** O campo onde estás
é o responsável por tudo o que vem antes do passo da partilha (as suas
leituras) e depois dele (o que a sua equipa faz com o que lê). **Só no passo
da partilha, os campos que a ligam são responsáveis conjuntos.** Perseguem
uma finalidade comum, a segurança das réplicas entre campos, através de um
sistema comum cujos meios aceitam em conjunto ao ligar a partilha. O operador
do hub trata as tabelas partilhadas como subcontratante desses campos em
conjunto. O essencial do acordo (os "termos de partilha", que cada campo
aceita no software; a aceitação, a sua versão e a data ficam registadas):

- **Âmbito:** só as leituras de cronógrafo assinadas de quem consentiu nos
  dois campos. Infrações, desfechos e nomes nunca passam.
- **Finalidade:** segurança das réplicas. Nunca marketing, pontuar pessoas
  nem recusar-te a entrada só com base nas leituras de outro campo: a equipa
  mede ela própria a réplica antes de decidir seja o que for.
- **Os teus direitos:** podes dirigir-te a **qualquer** campo participante;
  ele trata o pedido ou reencaminha-o em 7 dias. Retirar o consentimento e
  apagar funcionam logo no software.
- **Violações de dados:** o campo que a detetar avisa os outros e o operador
  do hub em 48 horas; cada um notifica a autoridade quanto aos seus dados.
- **Saída:** um campo que desligue a partilha deixa de ler, e as cópias que
  publicou são apagadas.

### 2.5 A tua posição (GPS, balizas Bluetooth)

Esta é a parte a ler com mais atenção.

- **Tu escolhes, no check-in.** Partilhar a posição é uma **opção à parte
  no check-in, nunca vem já marcada**, jogo a jogo. Nada se
  partilha por omissão. **Se recusares, podes fazer o check-in e jogar na
  mesma** (art. 7.º, n.º 4): recusar não bloqueia nada.
- **Podes parar a qualquer momento**, com um interruptor na app. Parar não
  afeta o que foi feito antes.
- **O que se partilha.** Enquanto partilhas e um jogo decorre, o teu
  telemóvel envia a última posição GPS (ou, em espaços fechados, **qual das
  balizas Bluetooth do campo ouve melhor**: uma sala, não um ponto ao
  metro) ao controlador do campo. O controlador guarda **só a última posição
  de cada jogador, para esse jogo, e apaga-a quando o jogo termina**. Não
  guarda o trajeto.
- **Balizas Bluetooth.** A app só escuta as balizas do próprio campo
  (registadas pelo campo) e só envia qual é a mais forte. O Android pede-te
  as permissões de Bluetooth e de localização para isso. Sem elas, usa-se só
  o GPS.
- **Quem a pode ver, no controlador:** tu; **o teu squad ou a tua equipa,
  conforme o modo de jogo permitir**; **os marshals e a organização,
  todos**; o token só de leitura do marcador, ninguém. Um modo de jogo pode
  deixar uma equipa ver outra durante algum tempo (por exemplo depois de um
  objetivo). No mapa, uma posição está ligada ao identificador pseudónimo da
  pessoa; os ecrãs da equipa podem mostrar o nome a mostrar junto dele.
- **Dispositivos ATAK da equipa no campo.** Se o campo usa ATAK, os
  dispositivos da equipa que o controlador do campo lista podem ver a
  posição de todas as pessoas que jogam na rede local do campo. As posições
  nunca são difundidas a outros dispositivos. [ESCOLHA DO CAMPO: se se usa
  ATAK.]
- **Organização remota e ATAK remoto (desligados por omissão).** **Uma
  pessoa da organização longe do campo só vê posições quando o campo liga a
  *organização remota* (`remote_gm`)**, e então só as de quem as partilha,
  **só em memória: o servidor não as guarda nem regista, nem o
  controlador**. Se o campo ligar também o ATAK remoto para quem joga
  (`remote_players`), o servidor reencaminha-as para dispositivos ATAK da
  organização e de marshals do campo cujo certificado foi emitido com esse
  direito, de novo sem as guardar. A app diz-to antes de partilhares.
  [ESCOLHA DO CAMPO: se estão ligados.]
- **Nunca:** as posições nunca vão pelo rádio do campo (LoRa), por MQTT, para
  outros campos, para o marcador, num evento ou num registo, nem para a base de
  dados do servidor.
- **Fundamento:** a) o teu consentimento, a opção à parte no check-in. Deixar
  a equipa ver as posições serve a finalidade a que consentes, a segurança e
  a gestão do jogo. A avaliação de impacto do campo cobre este controlo
  (`dpia-template-pt.md`).

### 2.6 Etiquetas NFC de jogador

Alguns modos de jogo usam uma etiqueta NFC (um autocolante, cartão,
porta-chaves ou pulseira) que levas contigo. A etiqueta tem o teu
**identificador de jogador no campo**, a tua equipa e o número do jogo, e
uma assinatura feita com a chave desse jogo. **Sem nome.** Uma caixa ou um
telemóvel que a leia verifica a assinatura; o número de série do chip é
comunicado mas nunca é de confiança. Gera-se uma chave nova em cada jogo,
por isso uma etiqueta de um jogo anterior deixa de funcionar. A etiqueta é
escrita pelo controlador do campo para o jogo, pela organização ou por um marshal. Fundamento: f) gerir o jogo [ADVOGADO: ou b)].

### 2.7 Histórico de jogos

Enquanto um jogo decorre, o controlador do campo regista os eventos do jogo
(uma caixa capturada, uma pontuação, uma etiqueta lida, uma cura), a
nomear quem joga **só pelo identificador pseudónimo**, nunca pelo nome. O
marcador mostra pontuações de equipas. Se o campo usa o servidor, o
controlador envia os eventos, as pontuações e os totais dos jogos, e vês na
tua conta os jogos em que os teus identificadores aparecem. Os outros
papéis no campo veem um jogo em curso com algum atraso (60 segundos, salvo
alteração do campo) e sem dados só da equipa nem identificadores; a equipa
vê tudo. **[ESCOLHA DO CAMPO:]** se o marcador público está ligado (está
desligado por omissão e mostra pontuações, não pessoas).

Os eventos, as pontuações e os nós de um jogo que levam o teu identificador
guardam-se **90 dias** depois de o jogo terminar, no controlador e no
servidor. Os resultados de equipa e de squad sem identificadores de pessoas
(sem listas de elementos; um squad com menos de 3 pessoas é incluído na sua
equipa) guardam-se **365 dias** (secção 7).

Fundamento: f) gerir os jogos e guardar o seu histórico [ADVOGADO:
confirmar].

### 2.8 Organização remota e ferramentas da equipa (servidor)

Se fazes parte da equipa: o servidor regista, por cada comando remoto que uma pessoa da organização enviou a um controlador (começar, pausar, retomar, terminar,
uma mensagem às caixas), a conta que o enviou, no controlador, durante 365
dias. Para os certificados ATAK regista o nome do dispositivo, quem o emitiu
e o endereço de cada ligação, no registo de segurança.

### 2.9 Clubes (servidor)

Se o servidor tem clubes: os clubes a que pertences e o teu papel, os
convites que recebeste e as denúncias de páginas públicas de clubes que
fizeste com sessão iniciada (nunca o teu endereço). As imagens que carregas
(logótipos, emblemas) devem ser imagens que tenhas o direito de usar e que não mostrem
o rosto de ninguém [ESCOLHA DO CAMPO]. Fundamento: [ADVOGADO: a) ou b)]; para
denúncias, f) moderação.

### 2.10 O que não fazemos

Não vendemos os teus dados, não os usamos para publicidade nem para criar
perfis, nem tomamos decisões sobre ti por meios automáticos. Os servidores
do próprio projeto não recebem os teus dados.

### 2.11 Os registos do anfitrião [RASCUNHO: a aguardar jurista]

O computador que corre o servidor (o do campo, o de um clube ou uma empresa de alojamento e, num hub alojado, quem o
opera) costuma guardar **registos próprios fora da base de dados do Atalaia**: o servidor web ou proxy (Caddy) e o
motor de contentores registam a hora, o teu endereço de rede, a página ou o caminho da API, o código de resposta e o
nome do navegador ou da app de cada pedido. Servem para pôr o serviço a funcionar e protegê-lo. **O apagamento e os
prazos do Atalaia não lhes chegam**; durante quanto tempo se guardam, e quem os pode ler, é escolha do anfitrião. A
configuração Docker do projeto roda-os por tamanho (cinco ficheiros de 10 MB), por isso duram dias ou semanas num
servidor sossegado. [ANFITRIÃO: indicar aqui o prazo real e quem tem acesso. ADVOGADO: fundamento (art. 6.º, n.º 1,
al. f), segurança), se o anfitrião é subcontratante do campo (acordo de subcontratação) e como um pedido de
apagamento deve tratar estes registos.]

## 3. Quem vê os teus dados (destinatários)

- **A equipa do campo**: administração, organização e marshals, conforme
  o papel (secção 2).
- **Quem joga**: a tua posição como em 2.5 apenas, e o que as regras
  do jogo do campo tornam visível (por exemplo a tua equipa e alcunha num
  jogo).
- **O operador do hub**, só se o servidor for alojado: guarda e faz cópias
  de segurança dos dados como subcontratante do campo, ao abrigo do acordo.
  Os seus subcontratantes: [LISTAR NO ANEXO DO ACORDO: FORNECEDOR DE
  ALOJAMENTO, ARMAZENAMENTO DE CÓPIAS].
- **Outros campos do mesmo hub alojado com quem escolheste partilhar**
  (opcional): só os campos onde ligaste as tuas contas **e em que
  consentiste**, e só enquanto os dois campos tiverem a partilha ligada:
  veem as leituras de cronógrafo da secção 2.4 (assinadas pelo marshal,
  com a chave pública do marshal), através de uma vista partilhada que o
  operador do hub mantém. Não veem mais nada da tua conta.
- **Fornecedores de início de sessão** (Google, Microsoft, Apple), se os
  usares: ver 6.
- **Fornecedores de mapas**, quando a organização carrega um mapa do
  campo: ver 6.
- **jogarairsoft.pt ou outro serviço de federação ou de seguros**:
  **[MARCADOR. Hoje não se envia nada ao jogarairsoft.pt nem a nenhuma
  associação. Se o campo fizer um acordo para verificar números de
  filiação ou enviar inscrições, este aviso tem de ser alterado primeiro,
  antes de enviar quaisquer dados: dizer o que se envia, com que fundamento,
  ao abrigo de que acordo e durante quanto tempo o parceiro o guarda.]**
- **Autoridades**, se a lei o exigir.

Não damos os teus dados a mais ninguém.

## 4. Como os dados circulam

### 4.1 Sem internet

O controlador do campo não precisa de internet. O check-in, o jogo, o
cronógrafo e a tua posição funcionam na rede Wi-Fi do próprio campo. O teu
nome, a tua preferência de equipa e as tuas réplicas declaradas (e, até o
check-in ser confirmado, o teu número de associado) **ficam no controlador e nunca são enviados ao servidor
nem a mais lado nenhum** (nomes e números do check-in nunca são enviados,
mesmo quando o controlador sincroniza).

### 4.2 Com o servidor (opcional)

Quando o controlador tem internet e o campo usa o servidor, o controlador
liga-se a ele (o servidor nunca se liga ao controlador) e envia: os jogos
com os seus eventos e pontuações, as leituras de cronógrafo (cada uma como
assinada), as réplicas, o resultado de cada inscrição (veio ou não veio), o
número de entradas sem inscrição como contagem e as chaves públicas dos marshals. Recebe o calendário, a lista de inscritos do próximo jogo, as
definições e a imagem do campo, cenários e, de quem consentiu, os registos
de cronógrafo de outros campos. Os dados viajam por HTTPS.

### 4.3 O teu telemóvel e o controlador

O teu telemóvel fala com o controlador do campo pela rede Wi-Fi do campo,
por HTTPS com a autoridade de certificação do próprio campo, que o código QR
do cartaz de check-in dá ao teu telemóvel.

## 5. Transferências para fora da UE/EEE

O controlador do campo não envia os teus dados para fora do campo. Os
telemóveis de quem joga e o controlador não contactam nenhum dos
destinatários abaixo.

| Destinatário | O que recebe | Iniciado por | Localização | Posição |
| --- | --- | --- | --- | --- |
| **Fornecedor de alojamento** de um servidor | Tudo o que está no servidor | O campo ou o operador do hub | **Só centros de dados na UE** | Um subcontratante indicado no acordo de subcontratação; sem transferência, porque está na UE |
| Uma **CDN, túnel ou proxy de DNS** à frente do servidor, se usado (por exemplo a Cloudflare) | Metadados do tráfego (endereços IP); o conteúdo, salvo se a cifra terminar no servidor | O operador | Muitas vezes uma empresa dos EUA | Um subcontratante; o Quadro de Privacidade de Dados UE-EUA (Decisão 2023/1795) se estiver certificado, senão cláusulas contratuais-tipo; ou não se usa nenhuma |
| **Início de sessão com Google, Microsoft, Apple** (opcional) | O teu navegador inicia sessão no fornecedor; o servidor recebe um identificador opaco | **Tu**, ao escolheres | Empresas dos EUA (com estabelecimentos na UE) | Responsáveis pelo tratamento distintos. O servidor do campo não exporta os teus dados para eles: interages diretamente com eles. Não os escolher não te custa nada |
| Mosaicos e pesquisa do **OpenStreetMap**; dados de mapa **Overpass** (overpass-api.de, overpass.private.coffee); a ortofotografia da DGT | O endereço IP **da organização** e a zona do mapa, só na página "Carregar o campo a partir de um mapa" | A equipa, ao preparar um campo | Fundação OpenStreetMap: Reino Unido (decisão de adequação). overpass-api.de: Alemanha. overpass.private.coffee: gerido pela Private.coffee, uma associação de direito austríaco; **a localização do servidor não é publicada e não está confirmada**. DGT: Portugal | Só dados da equipa, nenhum de quem joga. O campo pode **desligar a obtenção de mapas** nas suas definições, e então nada se vai buscar |

Se o campo usar um fornecedor de alojamento fora da UE, tem de o dizer aqui
e o acordo de subcontratação tem de indicar o instrumento de transferência
(uma decisão de adequação ou cláusulas contratuais-tipo).
[ESCOLHA DO CAMPO: o país e o fornecedor do centro de dados; se se usa uma
CDN; se a obtenção de mapas está ligada.]

## 6. Terceiros com quem te cruzas

- **Fornecedores de início de sessão: Google, Microsoft, Apple (só se os
  escolheres).** O teu navegador ou telemóvel vai ao fornecedor, que tem a
  sua política de privacidade e é responsável pelo tratamento do que guarda
  sobre ti. Enviam ao servidor um identificador opaco para ti (e o teu nome,
  só se carregares no botão que sugere um nome de utilizador a partir dele;
  não fica guardado). **O
  controlador do campo, as caixas e o modem do Atalaia nunca os contactam**;
  só o teu navegador e o servidor. Não os escolher não te custa nada: uma
  palavra-passe ou uma chave de acesso chega. O campo não envia os teus
  dados para eles (secção 5).
- **Mapas.** Só o *navegador* da organização, só na página "Carregar o
  campo a partir de um mapa", enquanto prepara o jogo, vai buscar mosaicos
  de mapa e pesquisa ao **OpenStreetMap**, dados de mapa a um servidor
  **Overpass** e, onde o país tem um, a um serviço aberto de ortofotomapas
  (em Portugal continental, o da DGT). Esses serviços veem o endereço da
  organização e a zona consultada (a secção 5 lista-os e diz onde estão).
  O campo pode desligar a obtenção de mapas. **Os
  telemóveis de quem joga e o controlador do campo não vão buscar mosaicos
  de mapa.** Se a organização não usar essa página, nada se vai buscar.
- **Chaves de acesso** usam o armazém de chaves de acesso do teu
  dispositivo ou navegador (por exemplo o Gestor de Palavras-passe da Google
  ou o Porta-chaves do iCloud, se usares um); o Atalaia nunca vê a chave
  privada.
- **jogarairsoft.pt**: **[MARCADOR: ver 3.]**
- **ATAK**, se usado, é uma app de terceiros nos dispositivos da equipa;
  guarda o que mostra segundo as suas próprias definições. [ESCOLHA DO
  CAMPO: a regra do campo para dispositivos ATAK da equipa.]

## 7. Durante quanto tempo guardamos

Estes são os prazos que o software aplica hoje. Um prazo marcado **[ESCOLHA
DO CAMPO]** é um que o campo pode alterar; os outros estão fixos no código.

| Dados | Onde | Guardados durante |
| --- | --- | --- |
| Conta (nome de utilizador, email, métodos de início de sessão, papéis, consentimentos) | servidor | Até apagares a conta |
| Sessões | servidor | 30 dias depois de terminarem ou caducarem; um início de sessão nunca concluído: 10 minutos |
| Registo de segurança | servidor | 36 meses; o **endereço de rede** de cada entrada só **180 dias** (quem gere o servidor pode definir 90 a 365), depois a entrada fica sem ele. Apagar a conta tira-lhe logo os teus endereços |
| Uma conta que ninguém usa há **24 meses** (sem início de sessão, chave de acesso ou login social, sem sessão, sem inscrição em jogo futuro; contas com papel num campo e administradores do servidor ficam de fora) | servidor | Um aviso na página da conta quando voltares, e 30 dias depois a conta é anonimizada (como se a tivesses apagado). O servidor não envia email, por isso **o aviso só chega se iniciares sessão**; quem gere o servidor pode desligar isto ou mudar os prazos |
| Uma nota que diz aos controladores de um campo para largarem as cópias de registos de cronógrafo de outros campos que obtiveram sobre ti (depois de apagares a conta ou retirares o consentimento de partilha de um campo). Só tem o teu identificador de jogador nesse campo | servidor | O prazo de conservação do campo (365 dias por defeito) |
| Os registos do próprio anfitrião (ver 2.11) | anfitrião | **[ESCOLHA DO ANFITRIÃO]** |
| O que resta de uma conta apagada (uma linha vazia com um nome aleatório `deleted-...`: sem nome, email, palavra-passe nem papéis) | servidor | Até ser apagada a última entrada do registo de segurança que a refere, no máximo 36 meses depois de usares a conta; depois a própria linha é apagada |
| Dados de inscrição de quem não tem conta (convidados importados) | servidor | 30 dias depois do jogo |
| O número de associado de uma inscrição | servidor | Apagado quando o check-in é confirmado; no máximo 30 dias depois do jogo |
| Reclamações de um identificador de jogador de um telemóvel | servidor | 30 dias depois de feitas |
| Jogos marcados e as suas inscrições | servidor | 24 meses depois de o jogo terminar |
| Jogos, os seus eventos, pontuações e nós (o teu histórico de jogos) | servidor | **Histórico de jogos com o teu identificador: 90 dias** depois de o jogo terminar |
| Resultados de equipa e de squad sem identificadores de pessoas (sem listas de elementos; um squad com menos de 3 pessoas é incluído na sua equipa) | controlador e servidor | **365 dias** depois de o jogo terminar |
| Leituras de cronógrafo, infrações, réplicas, chaves de marshals | servidor | **[ESCOLHA DO CAMPO:]** 365 dias por omissão, por campo (de 30 a 3653 dias, definidos por quem administra o campo) |
| O desfecho de um banimento | servidor | Até à sua **data de fim**: 12 meses por omissão, nunca mais do que as leituras de cronógrafo acima |
| O retrato do veredicto de uma verificação do cartão de associado (associação, validade, resultado, quem verificou) | controlador e servidor | Como os restantes dados do check-in (30 dias depois do jogo por omissão) |
| Pertença a clubes | servidor | Até saíres do clube ou apagares a conta |
| Convites de clubes não aceites | servidor | 30 dias |
| Denúncias de páginas de clubes | servidor | 12 meses depois de decididas |
| Certificados ATAK | servidor | Um certificado caduca em 7 dias por omissão (30 no máximo); o registo sai 30 dias depois de caducar |
| Imagens de identidade visual que nada usa | servidor | Um dia depois de carregadas |
| Registo da organização remota (que conta enviou um comando) | controlador | 365 dias |
| **Check-in: nome ou alcunha, preferência de equipa** | controlador | **[ESCOLHA DO CAMPO:]** 30 dias depois do jogo por omissão (`retention_days`), ou logo que saias do jogo na app |
| **Check-in: número de associado** | controlador | Apagado logo que o check-in é confirmado (o retrato do veredicto acima fica) |
| Réplicas declaradas num check-in | controlador | Os mesmos 30 dias |
| O identificador de campo que o teu telemóvel criou | controlador | Apagado ao fim de **um ano** sem check-in |
| Leituras de cronógrafo, leituras de outros campos recebidas para a lista de inscritos, chaves antigas de marshals | controlador | **[ESCOLHA DO CAMPO:]** 365 dias por omissão (de 30 a 3653): a mesma definição por campo do servidor, que o controlador adota quando o campo lhe vai buscar as definições |
| A tua posição | controlador | Até o jogo terminar, depois apagada. Só a última, nunca um trajeto |
| Eventos de jogo, pontuações, nós e a lista dos dispositivos de um jogo | controlador | **Histórico de jogos com o teu identificador: 90 dias** depois de o jogo terminar, e depois são apagados por inteiro; só nomeiam identificadores pseudónimos. Com um servidor do site configurado, o controlador nunca apaga um jogo antes de o servidor o ter por inteiro, pelo que um jogo que não consiga enviar fica (e o apagamento de uma pessoa feito no controlador chega sozinho ao servidor) |
| Posição, em memória (organização remota, ATAK remoto) | servidor | Não é guardada. Desaparece quando a ligação termina |

O servidor apaga o que passou destes prazos todos os dias (03:00 UTC); um
controlador verifica cerca de cada dez minutos. Cópias de segurança de um
servidor alojado: **[OPERADOR DO HUB: PRAZO DAS CÓPIAS, p. ex. 30 dias]**;
depois de um apagamento, os dados podem ficar numa cópia até esta caducar.

## 8. Os teus direitos

Podes, a partir da tua conta (servidor) ou no controlador:

- **Ver** tudo o que há sobre ti (acesso, art. 15.º): na app (dados do
  check-in) e na tua conta (`GET /me/data`): conta, papéis, sessões com
  endereços, as tuas entradas do registo, consentimentos, jogos, leituras de
  cronógrafo, réplicas, infrações, inscrições, reclamações, clubes,
  histórico, métodos de início de sessão e nomes das chaves de acesso.
- **Descarregar** (portabilidade, art. 20.º): um ZIP de ficheiros JSON com um
  README em inglês e em português.
- **Corrigir** (retificação, art. 16.º): o nome de utilizador, o email e a
  palavra-passe; no check-in, o teu nome e dados.
- **Apagar** (art. 17.º): na tua conta, com a palavra-passe (e o código da
  app de autenticação, se usares uma). A conta passa a um registo anónimo:
  sem nome, sem email, sem palavra-passe, sem consentimento; papéis, sessões,
  inícios de sessão sociais e chaves de acesso são **apagados**; as ligações
  aos identificadores de jogador são **apagadas**; as inscrições perdem a
  conta, o nome, a preferência de equipa, o número de associado e o bilhete
  (o resultado da inscrição fica como histórico do campo); a pertença a
  clubes e os convites são apagados; as tuas entradas do registo ficam sem
  endereços. **As leituras de cronógrafo assinadas e os resultados de jogos
  ficam, sem nada que os ligue a ti**, porque a segurança de quem joga e a
  integridade dos jogos dependem deles [ADVOGADO: confirmar o art. 17.º, n.º
  3, ou o argumento da anonimização]. No controlador, pede à organização
  que apague o teu identificador de jogador (check-ins e declarações; com as
  leituras, se pedires). **O último administrador de um servidor não pode ser
  apagado.**
- **Sair de um jogo**, na app: o teu check-in passa a "saiu" e o teu nome, o
  número de associado e a preferência de equipa são apagados.
- **Opor-te, limitar, retirar o consentimento** (art. 7.º, n.º 3, 18.º e
  21.º): no contacto da secção 1; deixar de partilhar a posição é um
  interruptor na app. Retirar o consentimento não afeta o que foi feito
  antes. A tua conta assenta em contrato, por isso podes apagá-la a qualquer
  momento (acima).
- **Contestar** um desfecho de infração ou um banimento (2.4): pelo mesmo
  contacto.
- **Não ficar sujeito a decisões automatizadas** (art. 22.º): não se toma
  nenhuma.

O campo responde em [ESCOLHA DO CAMPO: um mês, o limite do RGPD]. A
administração do campo pode também exportar todos os dados do campo (por
exemplo para os entregar a um novo operador ou responder a uma autoridade).

## 9. No teu telemóvel

A app Atalaia guarda os dados na pasta privada da própria app, que nenhuma
outra app lê. **As cópias de segurança estão desligadas**: os dados da app
não são copiados para a nuvem da Google. O que guarda: o último nome a
mostrar usado; se partilhas a posição (a última resposta); que versão do
aviso de cada campo leste; o identificador de campo e um segredo que o campo
usa para reconhecer o teu telemóvel; as tuas réplicas; os teus bilhetes de
inscrição; e, se usares uma conta do servidor, o token de renovação. **No
Android, os segredos** (a chave de adesão ao campo, a chave privada do marshal, o código de leitura, o teu segredo em cada campo e o token de
renovação do servidor) **estão selados com uma chave no Android Keystore** e
nunca num ficheiro legível. **Num iPhone, os mesmos segredos ficam na pasta
privada da app, protegidos pela proteção das apps do sistema; hoje não estão
no Porta-chaves** [RESPONSÁVEL DO PROJETO: confirmar a redação].
Desinstalar a app apaga tudo. A app não tem nenhuma biblioteca de análise,
publicidade ou relatórios de falhas.

## 10. Segurança

HTTPS entre todas as partes; palavras-passe como hashes Argon2id; segredos
TOTP cifrados; tokens de renovação guardados como hashes; dados separados
por campo com segurança ao nível da linha; os papéis da equipa só contam
numa sessão que passou o início de sessão em dois passos; bloqueios depois
de falhas repetidas; um registo de eventos de segurança. O controlador do
campo cria a sua própria autoridade de certificação.

Se houver uma violação de dados pessoais que te ponha em risco, informamos
a CNPD em 72 horas e a ti sem demora injustificada quando o risco for
elevado (art. 33.º e 34.º). [ALOJADO: o operador do hub informa o campo em
48 horas (acordo, secção 9).]

## 11. Crianças

Tens de ter **pelo menos 16 anos** para criar uma conta, e confirmas isso com
uma caixa de seleção ao criá-la (uma conta é um contrato, e a capacidade de
contratar de quem é mais novo é limitada: Código Civil, arts. 123.º e
seguintes e 127.º). Quem for mais novo joga pelo check-in do campo sem
conta, com o acordo de quem exerce as responsabilidades parentais que as
regras do próprio campo pedirem. [ESCOLHA DO CAMPO: a regra do campo para
quem tem menos de 16 ou de 18 anos.] O software não verifica idades para
além da caixa de seleção.

## 12. Reclamações

Tens o direito de apresentar reclamação à autoridade de controlo
portuguesa, a **Comissão Nacional de Proteção de Dados (CNPD)**, Av. D.
Carlos I, 134, 1.º, 1200-651 Lisboa, www.cnpd.pt [confirmar a morada antes
de usar], ou à autoridade do país da UE onde vives ou trabalhas.

## 13. Alterações

Se este aviso mudar, dizemos-to [ESCOLHA DO CAMPO: COMO: por email, na
página do campo, na app] antes de a alteração se aplicar. O servidor regista
a versão do aviso em que cada consentimento foi dado; um aviso alterado que
precise de novo consentimento pede-o: com a versão nova (e os ficheiros do
aviso novo na pasta `ATALAIA_PRIVACY_NOTICE_DIR`), cada conta é convidada a
ler o aviso e a consentir de novo na entrada seguinte, e a app pode fazer o
mesmo (`GET /api/v1/me` diz se o consentimento é da versão atual).

## 14. Contacto

[EMAIL OU MORADA DO CONTACTO DE PRIVACIDADE DO CAMPO]

---

# Parte B. Aviso na app ao criar uma conta

Texto curto para o ecrã *criar conta* da app (decisão S17-16). Tem de ser
mostrado **antes** de a conta ser criada, ligar ao aviso completo (Parte A)
e a pessoa tem de escolher continuar. Leva versão como a Parte A. Deve ter
mais ou menos este tamanho. O inglês está em `privacy-notice-en.md`.

> **A tua conta em [NOME DO CAMPO]**
>
> **[NOME LEGAL DA ORGANIZAÇÃO]** organiza os jogos em [NOME DO CAMPO] e é
> responsável pelos teus dados. Contacto: [EMAIL].
>
> **O que guardamos:** um nome de utilizador, um email se o deres, um
> método de início de sessão (palavra-passe, chave de acesso, ou início de
> sessão com Google, Microsoft ou Apple, caso em que só guardamos o
> identificador que esse fornecedor dá para ti, nunca o teu email nem nome;
> o nome do fornecedor só é lido se o pedires, para te sugerir um nome de
> utilizador, e não fica guardado),
> os teus papéis no campo, as tuas inscrições (um nome a mostrar, equipa e,
> se o jogo o pedir, um número de associado) e o teu histórico de jogos.
>
> **O que não guardamos:** a tua posição GPS (fica no controlador do campo
> durante um jogo e é apagada quando este termina), uma palavra-passe em
> forma legível, nem nada para publicidade.
>
> **Para quê:** dar-te uma conta, inscrever-te em jogos e guardar os teus
> registos de jogo e de segurança (leituras de cronógrafo).
> **Fundamento:** a conta é um contrato que pedes (art. 6.º, n.º 1, alínea
> b)). Partilhar a tua posição e partilhar com outros campos são escolhas
> separadas que fazes mais tarde; precisam do teu consentimento.
>
> **Durante quanto tempo:** até apagares a conta, com prazos mais curtos para
> algumas coisas. Os pormenores estão no aviso completo.
>
> **Os teus direitos:** ver, descarregar, corrigir e apagar os teus dados na
> app ("Conta"). Podes reclamar à CNPD (www.cnpd.pt).
>
> [ Ler o aviso completo ]
>
> Ao continuares confirmas que leste o aviso.
>
> [ ] Tenho pelo menos 16 anos.
>
> [ Criar a conta ]  [ Cancelar ]

O software regista que o aviso foi mostrado, com a sua versão
(`ATALAIA_PRIVACY_NOTICE_VERSION`), como um **registo de aviso mostrado**: a
conta assenta em contrato, não em consentimento. A caixa dos 16 anos tem de
estar marcada para "Criar a conta" funcionar.

---

# Parte C. Aviso curto para o cartaz e a página de check-in

Para o cartaz de check-in impresso do controlador do campo, ou para a página
que a app mostra ao abrir o código QR do cartaz. O texto por omissão do
controlador (`controller/templates/checkin-notice-pt.md`, preenchido com o
nome da organização e os dias de conservação) pode ser trocado por este
depois de revisto. No máximo um ecrã de texto.

> **Check-in em [NOME DO CAMPO]: os teus dados**
>
> **Quem:** [NOME LEGAL DA ORGANIZAÇÃO] ([EMAIL]) organiza o jogo e é
> responsável pelos teus dados.
>
> **O que guardamos no check-in:** o nome ou a alcunha que escreves, a tua
> preferência de equipa, as réplicas que declaras e a hora. Se o campo
> verificar o teu cartão de associado, a equipa olha para ele e guardamos só
> o resultado (associação, validade, válido ou não, quem verificou): **o
> número é apagado logo que o check-in é confirmado** (nada o verifica com
> ninguém). O
> teu telemóvel cria um identificador para este campo, e guardamos esse
> identificador e um hash do seu segredo. Não pedimos email, telefone, data
> de nascimento, documento nem fotografia.
>
> **A tua posição:** só se escolheres partilhá-la: uma caixa à parte no
> check-in, nunca vem já marcada. Se disseres que não, fazes
> o check-in e jogas na mesma, e podes parar de partilhar a qualquer
> momento. Fica no controlador do campo, só a última, e é apagada quando o
> jogo termina. Os marshals e a organização veem todos; o teu squad ou a tua
> equipa vê conforme as regras do jogo permitem. [ESCOLHA DO CAMPO, se ligado: "Se o campo tem uma organização
> remota, também a vê, em direto. Nada fica guardado."]
>
> **Para quê:** organizar o jogo e a segurança de quem joga (o cronógrafo).
> Os eventos do jogo e o marcador levam só o teu identificador, nunca o teu
> nome.
>
> **Quem vê:** a organização do campo. [Se o controlador sincroniza com um
> servidor:] O teu identificador, os eventos do jogo e as tuas leituras de
> cronógrafo são enviados ao servidor do campo; o teu nome e o número de
> filiação nunca são.
>
> **Durante quanto tempo:** o nome, a preferência de equipa e as réplicas
> declaradas são apagados [30] dias depois do jogo, ou logo que saias do jogo
> na app. Eventos e pontuações do jogo: 90 dias. Leituras de cronógrafo:
> [365] dias. Um banimento acaba ao fim de [12] meses, no máximo. O teu
> identificador de campo: um ano depois do último check-in.
>
> **Os teus direitos:** ver os teus dados na app; sair do jogo e apagá-los;
> pedir a [CONTACTO] que apague, corrija ou conteste o que quiseres
> (incluindo um banimento). Reclamações: CNPD, www.cnpd.pt.
>
> Aviso completo: [ENDEREÇO OU CÓDIGO QR].

---

# Parte D. O que está assente e o que continua em aberto

## Assente (2026-10-30)

O advogado do responsável pelo projeto aprovou, e o texto acima afirma agora:

1. Os **fundamentos** (2.1 a 2.4): conta e inscrição em contrato (art. 6.º,
   n.º 1, alínea b)) com um registo de aviso mostrado, segurança em f),
   registos de consentimento em c), consentimento mantido para a partilha
   entre campos, a partilha da posição e "usar o nome do meu fornecedor".
2. A **filiação numa associação** (2.3): não é uma categoria especial de
   dados; o cartão é verificado no check-in, o número apagado logo que o
   check-in é confirmado, o retrato do veredicto guardado; art. 6.º, n.º 1,
   alínea c) onde o campo tem o dever legal de verificar, senão f) ou b).
3. **Infrações e banimentos** (2.4): interesses legítimos, não são dados do
   art. 10.º, nenhuma decisão exclusivamente automatizada; os banimentos
   acabam ao fim de 12 meses por omissão e nunca depois do prazo de
   conservação do cronógrafo; o campo informa a pessoa; "reincidente" é
   indicativo e os simples avisos não contam; contestar faz-se pelo
   contacto do campo. AIPD: `dpia-template-pt.md`.
4. Os **papéis** (1, 2.4, 3): o campo é o responsável pelo tratamento; o
   operador do hub é o seu subcontratante (`dpa-template.md`); responsáveis
   conjuntos só no passo da partilha, com termos de partilha-tipo (art.
   26.º).
5. As **transferências** (5, 6): só centros de dados na UE; a tabela de
   destinatários; nenhuma transferência do campo para os fornecedores de
   início de sessão; uma definição para desligar a obtenção de mapas.
6. **Menores** (11): uma conta a partir dos 16 anos, confirmada por uma caixa
   de seleção.

Decidido pelo responsável pelo projeto em 2026-10-30, em linha com o
parecer aprovado:

7. **Encarregado de proteção de dados** (1): nenhum, com a justificação do
   art. 37.º, n.º 1, na secção 1.
8. **Dados de posição** (2.5): consentimento, pedido como uma opção à parte,
   não marcada, no check-in; recusar nunca bloqueia o check-in nem o jogo;
   diz-se quem a vê; a organização remota só quando o campo a liga.
9. **Histórico de jogos** (7): eventos, pontuações e nós com identificador guardam-se 90 dias
   no controlador e no servidor, e os resultados de equipa e de squad sem
   identificadores (sem listas de elementos; squads com menos de 3 incluídos
   na equipa) 365 dias; um controlador com sincronização nunca
   apaga um jogo antes de o servidor o ter por inteiro; as leituras de
   cronógrafo guardam-se 365 dias.

## Ainda em aberto

1. O **apagamento** (8): que as leituras de cronógrafo assinadas e os
   resultados de jogos possam ficar sem ligação à pessoa (art. 17.º, n.º 3,
   ou o argumento da anonimização).
2. **Outros fundamentos** que as posições aprovadas não cobrem: etiquetas
   NFC de jogador (2.6), histórico de jogos (2.7) e clubes (2.9).
3. **Pontos menores**: a redação sobre os segredos no iPhone (9) e a morada
   da CNPD (12), a confirmar antes de usar.
4. O **servidor de pré-visualização do próprio projeto** (um formulário de
   comentários que guarda um contacto opcional durante 90 dias e a mensagem
   durante 12 meses, sem conta nem endereço) tem um aviso próprio, em nome do
   projeto. Não faz parte deste aviso do campo.
