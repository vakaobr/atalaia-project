<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Acordo de subcontratação (modelo): servidor do site Atalaia alojado

> **Modelo, não é aconselhamento jurídico.** Um modelo do projeto Atalaia para
> um servidor do site alojado (ADR-P4-4, fase 21 do plano), em que uma parte
> gere o servidor de campos que não são seus. Segue o artigo 28.º, n.º 3, do
> RGPD. Os papéis (secção 2), o regime de partilha e a regra «só na UE»
> (secção 7) seguem as posições acordadas com o advogado do projeto (decisões
> LEG-40 a LEG-59). O texto final tem de ser verificado pelo advogado de quem
> o assinar, que conheça o RGPD e a Lei n.º 58/2019, e nenhum serviço alojado
> entra em funcionamento antes de estar completa a lista de verificação de
> entrada em produção de `server/docs/DEPLOY.md` («Hosted mode», decisão
> P4-6). O texto entre [PARÊNTESIS RETOS] é para preencher; **[ADVOGADO: ...]**
> marca uma escolha que ainda está em aberto. Mantém-se em linha com o
> tratamento que o software faz e com o aviso de privacidade do campo
> (`privacy-notice-pt.md`, Parte A). A versão em inglês é
> [`dpa-template.md`](dpa-template.md); as duas dizem o mesmo.

Entre **[DENOMINAÇÃO LEGAL DA ENTIDADE QUE GERE O CAMPO]**, [MORADA], [NIF] (o
**responsável pelo tratamento**), e **[DENOMINAÇÃO LEGAL DA OPERAÇÃO DO SERVIÇO
ALOJADO]**, [MORADA], [NIF] (o **subcontratante**), em conjunto as partes.

## 1. Objeto e duração

O subcontratante gere um servidor do site Atalaia para o(s) campo(s) do
responsável pelo tratamento [NOMES DOS CAMPOS] ao abrigo do contrato de serviço
de [DATA] (o serviço). Este acordo abrange os dados pessoais tratados no serviço
e dura enquanto o serviço durar, mais o tempo necessário para a secção 10.

## 2. Natureza e finalidade

Alojar, guardar, copiar e servir os dados que o servidor do site do responsável
pelo tratamento contém, para que este possa gerir os seus jogos: contas e
métodos de início de sessão, funções, sessões e o registo de segurança; [quando
usado:] jogos e resultados, registos de cronometragem, inscrições e jogos
agendados, clubes, a biblioteca de cenários, certificados ATAK, e a retransmissão
de dados em direto só em memória (a organização remota e o retransmissor remoto
de ATAK). O subcontratante executa também os comandos da própria operação por
instrução do responsável pelo tratamento (criar, suspender, retomar, exportar ou
apagar o campo do responsável, definir limites, um nome de anfitrião próprio).
Nenhuma outra finalidade: o subcontratante não lê os dados para fins próprios,
não cria perfis e não os vende nem partilha.

**Papéis.** O responsável pelo tratamento é o responsável pelos dados de cada
campo que gere. O subcontratante é o seu subcontratante (art. 28.º do RGPD) e
mantém um registo das atividades de tratamento que realiza como subcontratante
(art. 30.º, n.º 2). **Cada campo alojado é separado**: um esquema de base de
dados por campo, com segurança ao nível da linha, e uma conta num campo não está
ligada a uma conta noutro.

**A partilha de registos de cronometragem entre campos** é a única exceção, e só
quando o responsável pelo tratamento a liga (vem desligada). Nessa fase do
tratamento, publicar os registos de cronometragem assinados de uma pessoa para
os outros campos que partilham e ler os deles, os campos que partilham são
**responsáveis conjuntos** (art. 26.º) ao abrigo dos termos de partilha
(`sharing-terms-pt.md`, versão [VERSÃO]), que o responsável pelo tratamento
aceita no software quando liga a partilha (ficam registados a versão, a data e a
conta que aceitou). Antes dessa fase (os registos do próprio campo) e depois dela
(o que a equipa faz com o que lê) o responsável pelo tratamento é o único
responsável. Nas tabelas partilhadas o subcontratante atua **como subcontratante
dos campos que partilham, em conjunto**, segundo as instruções que estes termos e
este acordo dão, e a aceitação dos termos pelo responsável pelo tratamento é a
sua instrução para isso. O subcontratante não decide por si as finalidades nem
os meios da partilha.

## 3. Categorias de titulares e de dados

- Titulares: quem joga, a equipa (marshals, organização, administração) e quem se
  inscreve nos jogos do responsável pelo tratamento.
- Dados: nomes de utilizador, endereços de e-mail opcionais, *hashes* de
  palavras-passe, segredos de dois fatores cifrados, partes públicas e nomes das
  passkeys, inícios de sessão social ligados (só o nome do fornecedor e o seu
  identificador opaco; nem e-mail nem nome), funções, sessões (*hashes* dos
  tokens de renovação, endereços de ligação e agentes de utilizador), um registo
  de segurança, registos de consentimento; [quando usado:] identificadores de
  jogador pseudónimos por campo, eventos e pontuações de jogos, registos de
  cronometragem assinados, violações (com um indicador de reincidência),
  descrições de réplicas e entradas do registo, [quando a partilha entre campos
  está ligada:] as cópias partilhadas do hub dos registos de cronometragem
  assinados de quem ligou as contas e consentiu, as ligações e a aceitação dos
  termos de partilha pelo campo (versão, data, conta), dados de inscrição (um
  nome de apresentação, uma preferência de equipa, um número de associado
  opcional e a sua validade, um *hash* de um bilhete, se a pessoa veio ou pagou),
  clubes e os seus membros, certificados ATAK (nomes de dispositivos, quem os
  emitiu, endereços das ligações), o registo de comandos da organização remota
  (conta e comando), imagens que o responsável pelo tratamento carrega.
- As **posições** não são guardadas pelo servidor do site. Passam **só pela
  memória** para a organização remota e para o retransmissor remoto de ATAK,
  quando o responsável pelo tratamento os ligou, e não são guardadas nem
  registadas (decisão PKD-5). O subcontratante não as pode guardar, registar nem
  copiar, e os seus registos têm de estar configurados para que não apareçam em
  nenhum registo nem rasto.
- Não tratados: nomes de check-in, a chave do jogo, tokens (os tokens de GM e de
  leitura de um controlador nunca chegam ao servidor do site) e categorias
  especiais de dados (art. 9.º do RGPD): nenhum dos dados acima o é (a filiação
  numa associação desportiva não é). Também não são tratados pelo subcontratante
  os pedidos que a consola do próprio controlador faz ao OpenStreetMap, ao
  Overpass, ao Nominatim ou a serviços de imagem aérea quando a organização carrega
  um campo a partir de um mapa (o navegador pede-os a esses serviços; o controlador
  pode desligar isso, e o servidor do site não intervém).

## 4. Instruções

O subcontratante só trata os dados mediante instruções documentadas do
responsável pelo tratamento, sendo instruções este acordo e as definições do
responsável no serviço (e, para as tabelas partilhadas, os termos de partilha que
o responsável aceitou no serviço), sem nenhuma transferência para fora da UE/EEE
exceto como a secção 7 permite, salvo se o direito da União ou português exigir
outra coisa (caso em que o informa primeiro, salvo proibição dessa lei). Informa
logo o responsável se considerar que uma instrução viola a lei de proteção de
dados.

## 5. Confidencialidade

Todas as pessoas que podem aceder aos dados em nome do subcontratante estão
vinculadas a confidencialidade.

## 6. Segurança (art. 32.º do RGPD)

No mínimo: cifragem em trânsito (TLS) e em repouso [DESCREVER: cifragem de
disco, cópias de segurança cifradas]; os dados de cada campo no seu esquema de
base de dados com segurança ao nível da linha (ADR-P4-4); a função da base de
dados do servidor sem ser dona de nada e sem superutilizador nem contorno da
segurança ao nível da linha; acesso de administração só com início de sessão de
dois fatores; palavras-passe guardadas como *hashes* Argon2id, tokens de
renovação e bilhetes como *hashes* SHA-256, segredos de dois fatores e a chave da
AC do campo cifrados com a chave secreta do servidor, que o subcontratante guarda
fora da base de dados e das cópias de segurança; atualizações de segurança
aplicadas [EM N DIAS]; cópias de segurança diárias guardadas [30] dias e uma
restauração testada; os períodos de conservação do aviso de privacidade do
responsável aplicados pela limpeza diária (03:00 UTC, uma vez por campo); o
acesso da operação aos dados de um campo limitado ao que uma instrução exige, e
cada comando da operação escrito no registo de auditoria do hub com o seu motivo.
[ANEXO: a lista completa das medidas.]

## 7. Subcontratantes ulteriores, e onde estão os dados

**Localização: só centros de dados na UE.** O subcontratante aloja e guarda os
dados, incluindo todas as cópias de segurança, **só em centros de dados dentro da
União Europeia ou do Espaço Económico Europeu**, e escolhe os seus fornecedores
de alojamento e de cópias em conformidade. Não transfere os dados para um país
fora da UE/EEE, nem os deixa aceder a partir dele, salvo se o responsável pelo
tratamento tiver concordado por escrito, antecipadamente, e se aplicar uma
garantia do capítulo V (uma decisão de adequação, incluindo o Quadro de
Privacidade de Dados UE-EUA para um destinatário certificado; ou cláusulas
contratuais-tipo com uma avaliação do impacto da transferência), registada no
anexo. Se o próprio responsável escolher um fornecedor fora da UE/EEE, responde
pela licitude da transferência e o subcontratante só fica vinculado à garantia
que o responsável tiver registado no anexo.

O responsável pelo tratamento autoriza estes subcontratantes ulteriores, todos na
UE/EEE salvo se o anexo disser outra coisa nos termos do parágrafo anterior:
[FORNECEDOR DE ALOJAMENTO, A SUA MORADA, O PAÍS DO CENTRO DE DADOS]; [FORNECEDOR
DE ARMAZENAMENTO DE CÓPIAS, O PAÍS DO SEU CENTRO DE DADOS]; [QUALQUER TÚNEL, CDN
OU SERVIÇO DE DNS À FRENTE DO SERVIDOR, que vê o tráfego (endereços e, se o TLS não
terminar no subcontratante, o conteúdo): evitar um que seja empresa de fora da
UE, ou registar a sua garantia]; [SERVIÇO DE E-MAIL, se o servidor enviar
e-mail]. Os fornecedores de início de sessão (Google, Microsoft, Apple) **não**
são subcontratantes ulteriores: agem por conta própria, por escolha da pessoa, e
o servidor do site não lhes envia dados da pessoa. O subcontratante avisa o
responsável de qualquer alteração prevista com [N DIAS] de antecedência, e o
responsável pode opor-se. Cada subcontratante ulterior fica vinculado às mesmas
obrigações deste acordo, e o subcontratante continua responsável por ele.

## 8. Ajudar o responsável pelo tratamento

O subcontratante ajuda o responsável, na medida do possível, a responder aos
pedidos dos titulares (as funções de acesso, exportação, retificação e apagamento
do serviço, e a exportação de dados do próprio campo, fazem a maior parte disto),
e na segurança, na notificação de violações, nas avaliações de impacto sobre a
proteção de dados e na consulta prévia (art. 32.º a 36.º do RGPD). O apagamento
de uma pessoa, tal como o serviço o aplica (anonimiza a conta, apaga funções,
sessões, inícios de sessão social, passkeys e ligações a identificadores de
jogador, mantém os registos de cronometragem assinados e os resultados dos jogos
sem a ligação) é a forma escolhida pelo responsável; as cópias em cópias de
segurança são abrangidas pela secção 10. [ADVOGADO: confirmar.]

## 9. Violações de dados pessoais

O subcontratante informa o responsável pelo tratamento de uma violação de dados
pessoais sem demora injustificada e **em 48 horas** após ter conhecimento dela,
com o que souber (natureza, categorias e números aproximados de pessoas e
registos, consequências prováveis, medidas tomadas), para que o responsável possa
notificar a CNPD em 72 horas (art. 33.º do RGPD) e, se necessário, as pessoas
afetadas.

## 10. Fim do serviço

No fim do serviço o subcontratante, à escolha do responsável pelo tratamento,
devolve todos os dados (a `export` da operação ao esquema do campo: um ZIP com um
manifesto, um README e cada tabela em CSV, com o SHA-256 de cada ficheiro; ou a
exportação de dados do próprio campo) e/ou apaga-os (o comando `delete` da
operação para o campo), incluindo cópias e cópias de segurança em [30] dias, salvo
se o direito da União ou português exigir que os conserve; confirma o apagamento
por escrito.

## 11. Auditorias

O subcontratante disponibiliza toda a informação necessária para demonstrar que
cumpre este acordo e permite e contribui para auditorias, incluindo inspeções,
pelo responsável pelo tratamento ou por um auditor que este mandate, [COM N DIAS
DE AVISO, NO MÁXIMO UMA VEZ POR ANO, SALVO SE HOUVER UMA VIOLAÇÃO].

## 12. Lei e foro

Lei portuguesa; foro de [CIDADE].

Assinado: [LOCAL, DATA, NOMES, ASSINATURAS]
