<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Manual da administração do servidor do site

Para a administração e quem é GM de um campo no **servidor do site**, opcional: contas da organização e formas de entrar, as definições do campo, agendas e inscrições, a ligação aos controladores de campo, o GM remoto, a partilha de cronografagem e o modo alojado. Em inglês: [Site server administration manual](../en/site-admin.md). Dirigir um jogo no campo está no [Manual da organização](game-master.md).

> **Ainda não está pronto para o campo.** O servidor do site está feito e testado em software. Ainda não correu como instalação a sério. A instalação está no [guia do servidor do site](../../../server/README.md) (em inglês). Nenhum jogo fica à espera dele: um controlador joga sem ele e envia o que tem quando pode.

## Índice

1. [Contas, funções e entrar](#accounts-roles-and-logging-in)
2. [A página da tua conta](#your-account-page)
3. [As definições do campo](#the-fields-settings)
4. [Agendas e inscrições](#schedules-and-registration)
5. [Inscrições e a lista do dia](#registrations-and-the-game-day-roster)
6. [Ligar os controladores de campo](#connect-the-field-controllers)
7. [GM remoto](#remote-gm)
8. [As páginas da organização](#the-staff-pages)
9. [Partilha de cronografagem, reincidências e banimentos](#chrono-sharing-repeat-offenders-and-bans)
10. [Vários campos num servidor](#several-fields-on-one-server)
11. [Modo alojado](#hosted-mode)
12. [Dados e privacidade](#data-and-privacy)

<a id="accounts-roles-and-logging-in"></a>
## Contas, funções e entrar

As funções são por campo: `player`, `squad_leader`, `vip`, `marshal`, `gm`, `spectator` e `admin`. As funções `admin`, `gm` e `marshal` precisam de um **segundo fator**: um **código TOTP** de uma app de autenticação, ou uma **chave de acesso** (passkey; conta como os dois fatores de uma vez).

A primeira administração faz-se na linha de comandos do servidor:

```
docker compose exec server python -m atalaia_server create-admin --username NOME
```

**Entra** em `/staff/login`:

- com a tua palavra-passe e depois o código TOTP;
- com uma **chave de acesso** (*Entrar com chave de acesso*, sem nome de utilizador);
- com **Google**, **Microsoft** ou **Apple**, quando quem gere o servidor os ativou. A primeira entrada com um deles cria uma conta se marcares, junto dos botões, que leste o aviso de privacidade e que tens 16 anos ou mais. Só se guarda um identificador do fornecedor, nunca o teu email.

Entrar só com Google, Microsoft ou Apple não é segundo fator: cada página mostra então **Confirmar o segundo fator** (TOTP ou chave de acesso), e as tuas funções na organização contam a partir daí. Se o servidor desligou a entrada com palavra-passe, só aparecem a chave de acesso e os botões dos fornecedores.

Quando o aviso de privacidade do campo mudou desde a última vez que o viste, um painel **Aviso de privacidade** no topo pede-te que o leias e confirmes. É informação, não consentimento; entretanto nada fica bloqueado.

<a id="your-account-page"></a>
## A página da tua conta

A **Conta** (no topo à direita de cada página) tem as tuas formas de entrar. Cada alteração pede primeiro que confirmes que és tu: a palavra-passe atual ou, sem ela, o código TOTP, uma chave de acesso ou o fornecedor (vale 10 minutos).

- **Chaves de acesso**: *Adicionar chave de acesso*, dá-lhe um nome, confirma no navegador, no telemóvel ou na chave de segurança. Muda o nome ou remove uma.
- **Google, Microsoft, Apple**: *Ligar Google* (e por aí fora) ou desligar.
- **Palavra-passe**: definir, mudar ou remover.
- **Código TOTP**: ativar (junta o segredo à app de autenticação e escreve o código) ou desativar.
- **Nome de utilizador**: muda o nome da conta. Uma conta criada por uma primeira entrada com um fornecedor começa com **Escolher o nome de utilizador** (*Usar o meu nome de Google* só pergunta ao fornecedor quando carregas; *Ignorar por agora* deixa-o para depois).

A página diz por palavras porque recusa uma ação, por exemplo que é a última forma de entrar, ou que uma função da organização precisa de segundo fator. **Cria uma chave de acesso antes de largar o TOTP.**

Se ligares uma forma de entrar que já pertence a outra conta tua, a página oferece **Juntar a outra conta a esta**: as formas de entrar, as chaves de acesso e as funções passam para aqui, a palavra-passe não, e a outra conta fica fechada. Contas com função na organização não se juntam por este caminho.

<a id="the-fields-settings"></a>
## As definições do campo

A administração do campo (`admin`) abre **Definições** em `/staff/fields/<campo>/settings` (a ligação **Definições** nas secções do campo, ou em `/staff/`). Cada secção guarda-se à parte, e um valor recusado é explicado e nada dele fica guardado.

- **Página pública**: a página pública e os feeds ligados ou desligados, descrição, morada, rótulo da federação.
- **Regras de check-in**: o modelo de limites e o máximo de réplicas por pessoa.
- **Filiação numa APD / numa associação**: a lista aceite (ou qualquer), se a inscrição a exige, se é verificada no check-in, a validade, e as entradas próprias do campo.
- **Partilha de cronos**: vê [abaixo](#chrono-sharing-repeat-offenders-and-bans).
- **País**: `PT` diz **APD** e oferece as APD de Portugal; outro país (ou nenhum) diz **Filiação numa associação** e oferece as que o projeto conhece para ele.
- **Conservação de dados**: **Registos de cronografagem** e **Dados dos jogos**, em dias, de 30 a 3653 (365 e 90 por omissão). Vê [Dados e privacidade](#data-and-privacy).

No site, a administração define também a **identidade do campo** (nome, cor, logótipo, imagem de fundo) e as **equipas guardadas**.

Um controlador iniciado com `[sync] branding = "site"` recebe tudo isto do site, também um controlador de reserva. As mudanças chegam logo aos controladores ligados; os outros recebem-nas na sincronização seguinte. Num controlador assim, a consola não muda a identidade, o país nem a conservação, e uma mudança às definições do check-in só dura até à puxada seguinte.

<a id="schedules-and-registration"></a>
## Agendas e inscrições

**Criar um jogo agendado**

1. Nas páginas da organização, abre **Agenda**. Lista os jogos do campo (**Próximos**, **Passados** ou **Todos**), no fuso horário do campo.
2. Preenche o formulário no fim: título, início e fim, equipas, lugares, a janela de inscrição e se se pede o número de federado.
3. Toca em **Criar rascunho**. Um rascunho só aparece nas páginas da organização.
4. A administração toca em **Publicar** para o pôr na página pública e nos feeds. **Cancelar jogo** (com um motivo) cancela um jogo publicado.

Quem é `gm` cria, edita e apaga rascunhos e edita um jogo publicado, mas não publica nem cancela. Um jogo sem hora de abertura nem de fecho das inscrições não aceita inscrição online.

**Como se inscreve quem joga.** Um jogo publicado tem uma página pública em `/f/` *o campo* com um botão **Fazer a inscrição**, em português, inglês, alemão e chinês tradicional. Quem joga inscreve-se com uma conta:

- na app: **Participante › Inscrições online**;
- num navegador, sem a app: **Fazer a inscrição** e depois **Fazer a inscrição aqui** (`/f/<campo>/games/<jogo>/register/web`). Entra-se com Google, Microsoft ou Apple, com uma chave de acesso, ou com palavra-passe se o servidor as aceitar. A primeira entrada com um fornecedor cria a conta depois de a pessoa abrir o aviso de privacidade e marcar que o leu e que tem 16 anos ou mais.

Os dois seguem as mesmas regras (a janela, os lugares, o número de federado, a regra de APD do campo, as classes das réplicas). A pessoa recebe um **bilhete de check-in**, mostrado uma vez como código QR e como texto, para imprimir ou guardar. No campo, a mesa lê-o como um bilhete impresso ([Manual da organização](game-master.md#the-check-in-desk)). Contas novas na página web precisam da entrada com fornecedores configurada no servidor (`ATALAIA_OIDC_*`) e de um aviso de privacidade publicado. Uma conta faz no máximo 20 inscrições e bilhetes novos por hora. Ainda não testado numa instalação real nem num iPhone.

No controlador, **Check-in › Da agenda do site** transforma um jogo agendado num jogo em curso; quem se inscreveu aparece como **por chegar**.

<a id="registrations-and-the-game-day-roster"></a>
## Inscrições e a lista do dia

O botão **Inscrições** de um jogo publicado lista quem se inscreveu: nome no jogo, equipa pedida, número de federado (se pedido), réplicas, se há bilhete e o estado. Só a administração e quem é `gm` no campo o veem: são dados pessoais.

**Até o jogo começar**, a administração e quem é `gm` podem:

- **Editar** um nome, uma equipa, um número de federado ou as réplicas (**Juntar réplica**, **Tirar**);
- **Mudar de jogo** para outro jogo do campo que ainda não tenha começado. A pessoa, as réplicas e o bilhete mudam; a equipa e o número ajustam-se ao novo jogo e a página diz o que saiu;
- **Retirar** uma inscrição, ou **Repor** uma retirada, havendo lugar. Uma inscrição reposta fica sem bilhete: a pessoa toca em *Novo bilhete* na app, ou a mesa assinala o nome à chegada;
- **Marcar pago** e **Desmarcar pago**: só uma nota de quem marcou e quando. O servidor não recebe pagamentos.

**Depois do jogo**, **Sem comparência** marca quem não veio. O check-in do controlador prevalece sempre sobre a tua marca.

A **Lista do dia** mostra a lista que o controlador puxa (as inscrições ativas, pela ordem em que foram feitas). **Imprimir** dá uma cópia em papel com uma caixa para marcar por pessoa: imprime só o que o dia pede e destrói-a depois. A página diz também se o controlador já fez um jogo a partir dela, quantas chegadas sem inscrição comunicou, e quando um controlador puxou a lista pela última vez, com o nome da chave. As chegadas marcam-se no controlador, não aqui.

**Exportar e importar.** **Exportar CSV** guarda a lista (cada exportação fica registada, sem nomes). **Importar uma lista** lê um ficheiro CSV ou JSON com inscrições que o campo recebeu por outra via: dá um nome à origem, toca em **Verificar o ficheiro** (nada se guarda), marca que o campo tem fundamento próprio para a lista e toca em **Importar**. As inscrições importadas não têm conta nem bilhete.

**Filiação numa APD.** Quem joga declara a APD, o número de associado e a validade ao inscrever-se. A página das inscrições e a lista do dia mostram-nos com o veredicto (válida, caducada, não aceite, em falta), e a organização pode corrigi-los. A página pública diz o que o campo pede. A administração define a regra em **Definições**, ou pela API: `PATCH /api/v1/fields/{field}` com `{"apd": {"accepted": [...] ou null, "register": true, "checkin": true, "expiry": true, "custom": [...]}}` (as APD próprias do campo em `custom`, identificadores que começam por `x-`).

<a id="connect-the-field-controllers"></a>
## Ligar os controladores de campo

1. Obtém uma chave de API do campo no servidor do site ([guia do servidor do site](../../../server/README.md)). Dá a **cada controlador a sua própria chave, com um nome** (um campo pode ter duas ativas), para a lista do dia saber qual a puxou.
2. Num Pi, em `[sync]` no `controller.toml`: `enabled = true`, o `url` do servidor e a chave. Num telemóvel controlador: **Servidor do site, substituição e ATAK** nas definições da app.
3. Se quiseres:
   - `branding = "site"`: receber do site as definições, a identidade e as equipas guardadas do campo;
   - `push_walkins = true` (num telemóvel, **Enviar as chegadas sem inscrição ao servidor do site como convidados**): depois de um jogo feito a partir da agenda, quem veio sem inscrição vai para as **Inscrições** dele como convidado (nome, check-in feito, resultados de cronógrafo; sem conta, bilhete nem número). Desligado por omissão: o site recebe então só uma contagem;
   - `remote_gm = true`: vê [GM remoto](#remote-gm).
4. Reinicia o controlador.

O controlador é que abre todas as ligações, e nenhum jogo fica à espera da rede.

<a id="remote-gm"></a>
## GM remoto

Com `remote_gm = true` nas definições `[sync]` do controlador, quem é GM na página **GM remoto** do site:

- vê o jogo em curso, e as **posições de quem as partilha** (pessoa, equipa, função, onde, há quanto tempo; o site só as passa, não guarda nenhuma);
- pode **Começar**, **Pausa**, **Retomar**, **Terminar**, **Enviar mensagem**, **Enviar comando do modo** e **Desligar todas as saídas**. À distância nunca se liga uma saída.

**Começar** faz a mesma verificação da consola: se faltar um papel pergunta **Falta uma caixa (ou um telemóvel ligado) para: …. Começar mesmo assim?**. Cada comando fica registado nos dois lados.

<a id="the-staff-pages"></a>
## As páginas da organização

Páginas: **Campos**, **Histórico**, **Agenda**, **Cenários**, **Predefinições**, **Dispositivos**, **GM remoto**, **ATAK** e, para a administração, **Dados e limites**.

- **Histórico**: cada jogo com o resumo, a evolução da pontuação (em tempo de jogo; as pausas não contam) e o registo de acontecimentos. A página de um jogo só abre no campo a que pertence.
- **Dispositivos**: a saúde de cada caixa por palavras: **bateria fraca**, **desligada**, **em silêncio**, **violada**, **firmware desatualizado**.
- **Dados e limites** (a administração do campo): **Preparar a exportação** descarrega tudo o que o servidor guarda do campo num ZIP (dados pessoais: guarda-o com cuidado; credenciais, e-mails e endereços de rede não vão lá; cada exportação fica registada com o seu SHA-256). Num servidor alojado, uma tabela do que o campo usa de cada limite.
- **A página pública de um clube** lista os campos com página pública onde joga. As definições dela (a administração do campo) têm um **Marcador público**, um **Atraso para quem não é da organização** e **Guardar o histórico durante**.

<a id="chrono-sharing-repeat-offenders-and-bans"></a>
## Partilha de cronografagem, reincidências e banimentos

- **Partilha entre campos.** Em **Partilha de cronografagem**, nas **Definições** do campo, ligar a partilha exige que a administração (`admin`) aceite os termos de partilha. O campo continua responsável pelos dados de quem joga; os campos que partilham são corresponsáveis só nesse passo. Quando os termos mudam, a partilha fica em espera até a administração os aceitar de novo.
- **Reincidências.** A página **Cronografagem** do campo (`/staff/fields/<campo>/chrono`) marca quem reincide só como aviso; um simples aviso nunca conta.
- **Banimentos** registados aí terminam sozinhos ao fim do prazo do campo (12 meses por omissão, nunca mais do que a conservação da cronografagem).
- Quem joga contesta um registo pelo contacto do campo, como diz o aviso de privacidade.

<a id="several-fields-on-one-server"></a>
## Vários campos num servidor

Num servidor que aloja vários campos:

- **Cronografagem entre campos** (`/staff/account/hub-share`, ligada a partir da **Conta**) liga as tuas contas nos campos do servidor. Mostra o estado e os campos ligados, o **consentimento** que a partilha precisa neste campo (**Dar o consentimento**; **Retirar o consentimento** tira logo os registos deste campo da vista dos outros), **Gerar código** (aparece uma vez, vale 15 minutos e uma só utilização), **Escrever o código de outro campo** e **Desligar esta conta**. Um código gerado num campo não serve nesse mesmo campo; no máximo 10 códigos ou ligações por hora. Nada é partilhado se o interruptor do campo não estiver ligado e os termos aceites.
- **Jogos entre campos** (`/staff/fields/<campo>/hub-history`, para a administração, GM e marshals) partilha o histórico de jogos do campo com os outros campos que partilham o seu, **desligado por omissão**. A administração marca *Partilhar o histórico de jogos deste campo ...* e **Guardar**. Só passam resultados ao nível do jogo: o modo, as horas, a pontuação final de cada equipa, quem venceu e o nome do campo; nunca quem jogou, os acontecimentos, os squads nem os nomes escritos para o jogo ou para as equipas. Desligar retira logo todos os jogos partilhados. Quem opera o servidor lista o que é partilhado com `python -m atalaia_server hosted shared-history`.

Um servidor com um só campo não mostra nenhum dos dois.

<a id="hosted-mode"></a>
## Modo alojado

O espaço da comunidade prevê servidores geridos para clubes sem apoio informático, um por campo. Vem desligado por omissão e **ainda não é oferecido**. A assessoria jurídica aprovou as posições a 30 de outubro de 2026, mas há condições antes: um acordo de subcontratação assinado por campo, os termos de partilha, um aviso de privacidade preenchido, todos os subcontratantes na UE e uma prova num servidor real. Vê [o modo alojado](../../../server/README.md#hosted-mode) e [os modelos de privacidade e de tratamento de dados](../../README.md#templates) (em inglês).

<a id="data-and-privacy"></a>
## Dados e privacidade

- **Conservação.** Os **Registos de cronografagem** (o registo de leituras, infrações, réplicas e chaves de marshals, e as mesmas leituras nos controladores) e os **Dados dos jogos** (acontecimentos, pontuações e nós de um jogo terminado, nos controladores) guardam-se durante os dias definidos em **Definições › Conservação de dados** (365 e 90 por omissão). Um controlador só apaga um jogo depois de o servidor o ter por inteiro. O histórico de jogos do próprio servidor tem o seu prazo (a página **Histórico**).
- **Inscrições**: as inscrições importadas e os convidados sem inscrição são apagados 30 dias depois do jogo. O número de federado ou de associado, a APD e a validade são apagados 30 dias depois do jogo, e o número logo que o resultado do jogo chega do controlador ou o jogo termina.
- **Apagar a partir do campo.** Quando uma pessoa é apagada num controlador, o servidor do site apaga a sua cópia dos registos de cronografagem dela e a ligação do identificador a uma conta.
- **As contas** assentam no contrato, não no consentimento. Uma entrada com um fornecedor guarda só o identificador do fornecedor, nunca o email. Quem tem menos de 16 anos faz o check-in no campo sem conta.
- **As exportações** (CSV, ZIP, listas impressas) são dados pessoais: guarda-as só enquanto for preciso.
