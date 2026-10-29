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
> Como ler as marcas:
> - **[PARÊNTESES RETOS]**: o que o campo preenche (um nome, uma morada).
> - **[ESCOLHA DO CAMPO: ...]**: uma escolha que cabe à organização do campo
>   (um prazo, uma regra, se uma funcionalidade é usada).
> - **[ADVOGADO: ...]**: uma escolha jurídica que o código não pode fazer (um
>   fundamento, uma redação, um dever). Quando o rascunho propõe uma
>   resposta, di-lo.
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
> Versão: [draft-2026-10-28]

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

[ADVOGADO: se o campo tem de nomear um encarregado de proteção de dados
(RGPD, art. 37.º). Em regra não, num campo pequeno; se for o caso, diz-se
aqui: "Não nomeámos um porque ..." ou "O nosso encarregado de proteção de
dados é [NOME], [CONTACTO]."]

O Atalaia é software livre feito pelo projeto Atalaia. **O projeto não
recebe nem vê os dados deste campo.** Corre no equipamento do próprio campo
(ou num servidor que o campo escolheu). O projeto não é responsável pelo
tratamento dos teus dados aqui.

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
legítimos. **O software não pode decidir o fundamento**, por isso as tabelas
abaixo dizem o que o software faz e **propõem** um fundamento; quem decide é
o advogado. Onde o software regista um consentimento (a conta e a partilha
de cronógrafo), diz-se.

### 2.1 Conta e início de sessão (servidor)

| Dados | Para quê | Fundamento |
| --- | --- | --- |
| Nome de utilizador, email opcional, quando a conta foi criada e usada pela última vez | Dar-te uma conta | [ADVOGADO: a) consentimento, que o software regista quando te registas, ou b) contrato, pelo serviço que pedes] |
| **Palavra-passe**: apenas um hash Argon2id, nunca a palavra-passe. A palavra-passe é opcional | Iniciar sessão com palavra-passe | idem |
| **App de autenticação (TOTP)**: se está ativa e o segredo, guardado cifrado. Obrigatória para quem é marshal, da organização ou da administração | Um segundo passo no início de sessão; protege as contas da equipa | idem; para a equipa, também f) a segurança dos jogos |
| **Chaves de acesso** (passkeys, WebAuthn): um nome (teu, ou dado pelo servidor), o nome do anfitrião e as datas. O servidor guarda só a parte pública; **nunca** a chave privada nem o identificador da chave de acesso | Iniciar sessão sem palavra-passe | idem |
| **Início de sessão com Google, Microsoft ou Apple**: **só o nome do fornecedor e o identificador opaco ("subject") que o fornecedor dá para ti, e quando o ligaste**. O servidor não pede email, fotografia nem mais nada ao iniciares sessão. **Uma exceção, só quando carregas em "Usar o meu nome de Google" ou "Usar o meu nome de Microsoft" na página da tua conta**: o fornecedor diz então também o teu nome ao servidor, uma vez, para te sugerir um nome de utilizador. **Esse nome só é lido porque o pediste, é transformado numa sugestão que podes editar e não fica guardado**: só se guarda o nome de utilizador que confirmares. O fornecedor fica a saber em que site estás a entrar, como em qualquer início de sessão social | Iniciar sessão sem palavra-passe | idem |
| Os teus **papéis** no campo (participante, líder de squad, VIP, marshal, organização, espectador, administração) | Deixar-te fazer o que o papel permite | idem; para a equipa também f) |
| Sessões: um hash do token de renovação, o endereço e o navegador ou app de cada início de sessão, as horas | Manter a sessão e a conta seguras | f) segurança do serviço |
| **Registo de segurança**: inícios de sessão, falhados, bloqueios, alterações à conta, papéis atribuídos, com o endereço. Nunca uma palavra-passe nem um código | Segurança e responsabilização | f) |
| **Registos de consentimento**: o que aceitaste, que versão do aviso, quando | Provar o consentimento (art. 7.º, n.º 1) | c) |

### 2.2 Inscrição num jogo e check-in

| Dados | Para quê | Fundamento |
| --- | --- | --- |
| **Inscrição (servidor)**: o teu identificador de jogador no campo, um nome a mostrar no jogo (por omissão o teu nome de utilizador), a preferência de equipa, o teu **número de associado** se o jogo o pedir, as réplicas que declaras, se vieste ou não, se pagaste (o campo anota; nenhum pagamento é processado) | Organizar o jogo | [ADVOGADO: b) contrato, pelo jogo em que te inscreves, ou f)] |
| Um **bilhete de inscrição**: um segredo aleatório mostrado uma vez; só se guarda um hash | Associar a tua chegada à inscrição | idem |
| **Check-in no campo (controlador)**: o nome ou a alcunha que escreves, a preferência de equipa, as réplicas que declaras, **o teu número de associado e a validade** se o campo os pedir (o check-in diz à equipa se parece válido, caducado, não aceite ou em falta; **nada verifica o número com ninguém**), a hora. O teu telemóvel cria um identificador para este campo; o controlador guarda-o e um hash do segredo que o acompanha. **Não se pede email, telefone, data de nascimento, documento de identificação nem fotografia** | Gerir o jogo e saber quem está no campo | [ADVOGADO: f) o interesse do campo em jogos seguros, ou b)] |
| **Número de associado e validade**: ver 2.3 | | |
| Um marshal ou a organização pode confirmar ou fazer o check-in à mão mesmo que a verificação da filiação falhe. Fica registado com o identificador da pessoa e o veredicto, nunca o número | Decisão da equipa | f) |

### 2.3 Números de associado (APD) e validade

Alguns campos pedem a filiação numa associação de airsoft (em Portugal,
uma "APD"; noutros países, um clube, uma federação ou uma seguradora). O
software só guarda o que escreves: a associação, o número e a data de
validade, e diz à equipa "válido", "caducado", "não aceite" ou "em falta".
Nunca verifica o número com a associação nem com mais ninguém. O número de
filiação não é mostrado a quem joga, ao marcador só de leitura nem em
nenhum evento, registo ou mensagem MQTT; a equipa (organização, marshals)
vê-o.

[ESCOLHA DO CAMPO: se o campo o pede de todo, e se é preciso para jogar ou
só para se inscrever.]
[ADVOGADO: o fundamento. Proposta: f), ou c) se o seguro do campo ou a lei
exigir prova de filiação; dizer qual. A filiação numa associação de airsoft
não é, à primeira vista, uma categoria especial de dados (art. 9.º);
confirmar.]

### 2.4 Leituras de cronógrafo, réplicas e reincidentes

| Dados | Para quê | Fundamento |
| --- | --- | --- |
| As **réplicas** que declaras ou que o campo regista por ti: tipo, classe, marca e modelo, um identificador num **autocolante NFC ou numa etiqueta QR** (`ATL-` e oito caracteres: nada pessoal na etiqueta em si, mas o registo do campo liga-a a ti) | Segurança: limites de potência das réplicas | f) segurança de quem joga |
| **Leituras de cronógrafo** (a energia de um tiro, a hora, o check-in ou a verificação pontual, o resultado passa, aviso ou falha), **assinadas pelo marshal**; a chave pública do marshal | Segurança | f) |
| **Infrações**: uma verificação pontual que falhou ou deu aviso, quanto passou do limite, e se és **reincidente** (tens uma infração anterior neste campo). A equipa regista o que foi feito | Segurança; deixar a equipa ver o histórico antes de decidir | f) [ADVOGADO: confirmar que mostrar à equipa a marca de "reincidente", que é só um indicador e não uma decisão, é proporcionado; confirmar que não há "decisão exclusivamente automatizada" (art. 22.º). O software não decide nada sozinho: uma pessoa confirma cada consequência.] |
| **Partilha com outros campos** (opcional): se dois campos a ativarem **e consentires em cada um dos dois**, a equipa do outro campo vê as tuas leituras, cada uma com a chave pública do marshal. Os identificadores de cada campo nunca são cruzados: só uma conta que tenha ambos os liga. Num **hub alojado**, onde cada campo tem as suas contas, ligas tu as tuas contas com um código de uso único; o operador do hub guarda então, por cada campo em que consentiste, uma cópia das leituras assinadas desse campo sobre ti nas tabelas de partilha do hub, e só os campos em que consentiste a podem ler. Retirar o consentimento, desligar as contas ou apagar a conta remove essa cópia | Outro campo ver o historial de uma réplica | a) o teu consentimento próprio, por campo, que podes retirar na tua conta |

### 2.5 A tua posição (GPS, balizas Bluetooth)

Esta é a parte a ler com mais atenção.

- **Tu escolhes, jogo a jogo.** A app pergunta em cada jogo se queres
  partilhar a posição. Nada se partilha por omissão.
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
- **Quem a pode ver, no controlador:** tu; o teu squad, se o jogo o permitir; quem lidera um squad, o seu squad; um VIP, a sua equipa;
  **os marshals e a organização, todos**; o token só de leitura do
  marcador, ninguém. Um modo de jogo pode deixar uma equipa ver outra durante
  algum tempo (por exemplo depois de um objetivo). No mapa, uma posição está
  ligada ao identificador pseudónimo da pessoa; os ecrãs da equipa podem
  mostrar o nome a mostrar junto dele.
- **Dispositivos ATAK da equipa no campo.** Se o campo usa ATAK, os
  dispositivos da equipa que o controlador do campo lista podem ver a
  posição de todas as pessoas que jogam na rede local do campo. As posições nunca
  são difundidas a outros dispositivos. [ESCOLHA DO CAMPO: se se usa ATAK.]
- **Organização remota e ATAK remoto (desligados por omissão).** Se o
  campo ligar a *organização remota* (`remote_gm`), uma pessoa da organização com sessão no servidor, longe do campo, vê também as posições de quem as
  partilha, **só em memória: o servidor não as guarda nem regista, nem o
  controlador**. Se o campo ligar também o ATAK remoto para quem joga
  (`remote_players`), o servidor reencaminha-as para dispositivos ATAK de
  da organização e marshals do campo cujo certificado foi emitido com esse
  direito, de novo sem as guardar. A app diz-to antes de partilhares.
  [ESCOLHA DO CAMPO: se estão ligados.]
- **Nunca:** as posições nunca vão pelo rádio do campo (LoRa), por MQTT, para
  outros campos, para o marcador, num evento ou num registo, nem para a base de
  dados do servidor.
- **Fundamento:** a) o teu consentimento, dado na app em cada jogo, que
  podes retirar a qualquer momento deixando de partilhar. [ADVOGADO:
  confirmar que o consentimento é o fundamento certo e que a equipa ver
  todas as posições cabe na finalidade "segurança e gestão do jogo".]

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
nome, o teu número de associado, a tua preferência de equipa e as tuas
réplicas declaradas **ficam no controlador e nunca são enviados ao servidor
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

O controlador do campo não envia os teus dados para fora do campo.

[SE FOR ALOJADO ou se o campo usar um servidor no estrangeiro: O servidor
está em **[PAÍS DO CENTRO DE DADOS]**. [ADVOGADO: se for fora da UE/EEE, o
instrumento de transferência: uma decisão de adequação ou cláusulas
contratuais-tipo, conforme o acordo.]]

Se iniciares sessão com Google, Microsoft ou Apple, esse fornecedor (uma
empresa com atividade nos Estados Unidos) fica a saber que estás a entrar
neste site; ver 6.

## 6. Terceiros com quem te cruzas

- **Fornecedores de início de sessão: Google, Microsoft, Apple (só se os
  escolheres).** O teu navegador ou telemóvel vai ao fornecedor, que tem a
  sua política de privacidade e é responsável pelo tratamento do que guarda
  sobre ti. Enviam ao servidor um identificador opaco para ti (e o teu nome,
  só se carregares no botão que sugere um nome de utilizador a partir dele;
  não fica guardado). **O
  controlador do campo, as caixas e o modem do Atalaia nunca os contactam**;
  só o teu navegador e o servidor. Não os escolher não te custa nada: uma
  palavra-passe ou uma chave de acesso chega. [ADVOGADO: as regras de
  transferência para estes fornecedores.]
- **Mapas.** Só o *navegador* da organização, só na página "Carregar o
  campo a partir de um mapa", enquanto prepara o jogo, vai buscar mosaicos
  de mapa e pesquisa ao **OpenStreetMap** e, onde o país tem um, a um
  serviço aberto de ortofotomapas (em Portugal continental, o da DGT). Esses
  serviços veem o endereço da organização e a zona consultada. **Os
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
| Registo de segurança | servidor | 36 meses. Apagar a conta tira-lhe os endereços |
| Dados de inscrição de quem não tem conta (convidados importados) | servidor | 30 dias depois do jogo |
| O número de associado de uma inscrição | servidor | 30 dias depois do jogo |
| Reclamações de um identificador de jogador de um telemóvel | servidor | 30 dias depois de feitas |
| Jogos marcados e as suas inscrições | servidor | 24 meses depois de o jogo terminar |
| Jogos, os seus eventos e pontuações (o teu histórico de jogos) | servidor | **[ESCOLHA DO CAMPO:]** 24 meses depois de o jogo terminar, ou menos se o campo o definir |
| Leituras de cronógrafo, infrações, réplicas, chaves de marshals | servidor | **[ESCOLHA DO CAMPO:]** 365 dias por omissão, por campo (de 30 a 3653 dias, definidos por quem administra o campo) |
| Pertença a clubes | servidor | Até saíres do clube ou apagares a conta |
| Convites de clubes não aceites | servidor | 30 dias |
| Denúncias de páginas de clubes | servidor | 12 meses depois de decididas |
| Certificados ATAK | servidor | Um certificado caduca em 7 dias por omissão (30 no máximo); o registo sai 30 dias depois de caducar |
| Imagens de identidade visual que nada usa | servidor | Um dia depois de carregadas |
| Registo da organização remota (que conta enviou um comando) | controlador | 365 dias |
| **Check-in: nome ou alcunha, número de associado e validade, preferência de equipa** | controlador | **[ESCOLHA DO CAMPO:]** 30 dias depois do jogo por omissão (`retention_days`), ou logo que saias do jogo na app |
| Réplicas declaradas num check-in | controlador | Os mesmos 30 dias |
| O identificador de campo que o teu telemóvel criou | controlador | Apagado ao fim de **um ano** sem check-in |
| Leituras de cronógrafo, leituras de outros campos recebidas para a lista de inscritos, chaves antigas de marshals | controlador | **[ESCOLHA DO CAMPO:]** 365 dias por omissão (de 30 a 3653): a mesma definição por campo do servidor, que o controlador adota quando o campo lhe vai buscar as definições |
| A tua posição | controlador | Até o jogo terminar, depois apagada. Só a última, nunca um trajeto |
| Eventos de jogo, pontuações e a lista dos dispositivos de um jogo | controlador | **[ESCOLHA DO CAMPO:]** 365 dias por omissão (de 30 a 3653) depois de o jogo terminar, e depois são apagados por inteiro; só nomeiam identificadores pseudónimos. Com um servidor do site configurado, o controlador nunca apaga um jogo antes de o servidor o ter por inteiro, pelo que um jogo que não consiga enviar fica (e o apagamento de uma pessoa feito no controlador chega sozinho ao servidor) |
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
  antes. Retirar o consentimento da conta significa apagá-la.
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
no Porta-chaves** [ADVOGADO / RESPONSÁVEL DO PROJETO: confirmar a redação].
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

[ADVOGADO: idade mínima. Na lei portuguesa, uma criança com 13 anos ou mais
pode consentir em serviços da sociedade da informação (Lei n.º 58/2019, art.
16.º); abaixo disso, quem exerce as responsabilidades parentais. Muitos
campos fixam também uma idade mais alta para jogar. Dizer aqui o que o campo
exige: "Tens de ter pelo menos [IDADE] anos para criar uma conta. Quem
exerce as responsabilidades parentais regista quem for mais novo."] O
software não verifica idades.

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

Texto curto para o ecrã *criar conta* da app (decisão S17-16; hoje a app não
cria contas, isto espera por este aviso e pela revisão jurídica). Tem de ser
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
> [ADVOGADO: o fundamento: consentimento ou contrato.]
>
> **Durante quanto tempo:** até apagares a conta, com prazos mais curtos para
> algumas coisas. Os pormenores estão no aviso completo.
>
> **Os teus direitos:** ver, descarregar, corrigir e apagar os teus dados na
> app ("Conta"). Podes reclamar à CNPD (www.cnpd.pt).
>
> [ Ler o aviso completo ]
>
> [ ] Li o aviso e aceito criar a conta. [ADVOGADO: manter a caixa se o
> fundamento for o consentimento; com outro fundamento, trocar por "Ao
> continuares confirmas que leste o aviso".]
>
> [ Criar a conta ]  [ Cancelar ]

O software regista a aceitação com a versão do aviso
(`ATALAIA_PRIVACY_NOTICE_VERSION`), como um consentimento com a finalidade
`account`.

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
> preferência de equipa, as réplicas que declaras, o teu número de associado
> e a validade se o campo os pedir (nada os verifica com ninguém) e a hora. O
> teu telemóvel cria um identificador para este campo, e guardamos esse
> identificador e um hash do seu segredo. Não pedimos email, telefone, data
> de nascimento, documento nem fotografia.
>
> **A tua posição:** só se escolheres partilhá-la, durante um jogo. Fica no
> controlador do campo, só a última, e é apagada quando o jogo termina. A
> organização vê todos; quem joga vê só o que as regras do jogo
> permitem. [ESCOLHA DO CAMPO, se ligado: "Se o campo tem uma organização
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
> **Durante quanto tempo:** o nome, o número de associado, a preferência de
> equipa e as réplicas declaradas são apagados [30] dias depois do jogo, ou
> logo que saias do jogo na app. Leituras de cronógrafo: [365] dias. O teu
> identificador de campo: um ano depois do último check-in.
>
> **Os teus direitos:** ver os teus dados na app; sair do jogo e apagá-los;
> pedir a [CONTACTO] que apague ou corrija o que quiseres. Reclamações:
> CNPD, www.cnpd.pt.
>
> Aviso completo: [ENDEREÇO OU CÓDIGO QR].

---

# Parte D. Pontos para o advogado

O rascunho não os pode resolver. Cada um está marcado **[ADVOGADO]** acima.

1. Os **fundamentos** de cada finalidade (2.1 a 2.9); em especial se uma
   conta e uma inscrição ficam melhor com base em contrato (art. 6.º, n.º
   1, alínea b)) do que em consentimento, sendo que o software regista hoje
   um consentimento com a finalidade `account`.
2. Os **números de associado** (2.3): o fundamento, e se alguma regra do
   campo ou o seguro do campo o torna uma obrigação legal.
3. Os **dados de posição** (2.5): consentimento em cada jogo, a equipa ver
   todas as pessoas que jogam, a organização remota e o ATAK remoto; se é
   preciso uma avaliação de impacto sobre a proteção de dados (art. 35.º).
4. **"Reincidente"** (2.4): a proporcionalidade de o mostrar à equipa.
5. O **apagamento** (8): que as leituras de cronógrafo assinadas e os
   resultados de jogos possam ficar sem ligação à pessoa.
6. Os **papéis de responsável e subcontratante** (1) num servidor alojado, e
   o acordo (`dpa-template.md`).
7. As **transferências** (5, 6): fornecedores de início de sessão; o país
   do alojamento.
8. **Menores** (11).
9. **Encarregado de proteção de dados** (1).
10. Os **eventos de jogo do controlador** (7): apagados 365 dias por omissão
    depois de o jogo terminar (uma definição do campo, de 30 a 3653 dias): se esse
    valor por omissão é proporcional, e se um jogo que o servidor nunca recebeu
    deve ficar além dele.
11. O **servidor de pré-visualização do próprio projeto** (um formulário de
    comentários que guarda um contacto opcional durante 90 dias e a
    mensagem durante 12 meses, sem conta nem endereço) precisa de um aviso
    próprio, em nome do projeto. Não faz parte deste aviso do campo.
