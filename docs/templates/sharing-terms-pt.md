<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Termos de partilha: partilha de registos de cronometragem entre campos (artigo 26.º do RGPD)

**Versão 2026-10-30.** A versão está em `atalaia_server/sharing_terms.py` (`DEFAULT_VERSION`) e é o que o software
regista quando um campo aceita estes termos. Mudando o texto, muda-se a versão: todos os campos são então convidados a
aceitar de novo e a sua partilha fica suspensa até o fazerem. A versão em inglês está em
[`sharing-terms.md`](sharing-terms.md); as duas dizem o mesmo.

> **Modelo, não é aconselhamento jurídico.** O regime segue as posições acordadas com o advogado do projeto (decisões
> LEG-40 a LEG-59). Um operador de hub ou um campo que o adote deve pedir ao seu próprio advogado que reveja a
> redação final. O texto entre [PARÊNTESIS RETOS] é preenchido por quem publica os termos.

Estes termos são o **acordo entre responsáveis conjuntos** que o artigo 26.º do RGPD exige. Aceitam-se **no software**,
pela administração do campo, quando o campo liga a partilha de cronos entre campos (a página de definições do
servidor, secção «Termos de partilha»). O software regista que versão foi aceite, quando, e por que conta. Ninguém
negoceia com outro campo: todos os campos que partilham aceitam os mesmos termos.

## 1. Partes

Os **campos** que têm a partilha de cronos ligada no mesmo hub ou servidor do site (cada um, um **campo**; em conjunto,
os **campos**). Cada campo é representado pela pessoa coletiva que o gere (um clube, uma associação ou uma empresa). A
**operação do hub** ([DENOMINAÇÃO LEGAL DA OPERAÇÃO DO HUB]) gere o servidor e não é parte: é subcontratante (secção 3).

## 2. O que estes termos abrangem, e o que não abrangem

A partilha entre campos é uma fase do tratamento: um campo **publica** os registos de cronometragem assinados de uma
pessoa para os outros campos que partilham, e a equipa desses campos **lê-os**. Estes termos abrangem só essa fase.

Cada campo continua a ser **único responsável** por tudo o que vem antes (os registos que faz, guarda e assina no seu
campo) e depois (o que a sua equipa decide, regista ou faz com o que lê, incluindo qualquer violação ou decisão). Essas
partes regem-se pelo aviso de privacidade do próprio campo, e não por estes termos.

## 3. Papéis

1. Cada campo é **responsável pelo tratamento** dos dados de quem joga no seu campo.
2. A **operação do hub** é **subcontratante** de cada campo ao abrigo do acordo de subcontratação (`dpa-template-pt.md`,
   art. 28.º, n.º 3). Nas tabelas partilhadas trata os dados **como subcontratante dos campos em conjunto**, nestes
   termos.
3. Só para a fase da partilha, os campos são **responsáveis conjuntos** (art. 26.º): prosseguem uma finalidade comum (a
   segurança das réplicas entre campos) através de um sistema cujos meios aceitam em conjunto ao ligar a partilha.
4. O projeto Atalaia (quem escreve o software livre) **não** é responsável pelo tratamento nem subcontratante dos dados
   de nenhum campo.
5. Os dados só são tratados no hub ou no servidor do site que os campos usam, num centro de dados na UE/EEE, como o
   acordo de subcontratação exige. Estes termos não acrescentam nenhuma transferência para fora da UE/EEE.

## 4. Âmbito dos dados

Só os **registos de cronometragem assinados** de quem deu consentimento para **os dois** campos, o que fez o registo e
o que o lê: o registo assinado exatamente como o telemóvel do marshal o assinou (com a chave pública do marshal), e mais
nada. **Não se partilham:** nomes, violações, o que a equipa decidiu, dados de check-in, dados de inscrição, posições e
quaisquer outros dados da pessoa. As contas da pessoa em dois campos só são ligadas pela própria pessoa, com um código
de uso único; nada se cruza por endereço de e-mail nem por nome de utilizador.

## 5. Finalidade, e o que não se pode fazer

A finalidade é a **segurança das réplicas**: um campo pode ver que uma réplica mediu acima do limite noutro campo antes
de a deixar jogar.

Os registos partilhados **nunca** se usam para marketing, para pontuar ou classificar pessoas, nem para **recusar a
entrada só com base nos registos do outro campo**: a equipa mede sempre a réplica antes de decidir seja o que for. O
campo que use um registo partilhado para outra finalidade é o único responsável por essa utilização e viola estes
termos.

## 6. Fundamento de licitude, e escolhas da pessoa

O fundamento é o **consentimento da pessoa** (art. 6.º, n.º 1, alínea a)), pedido **em separado para cada campo**: a
pessoa pode partilhar com um campo e não com outro. O ecrã de consentimento diz que campos partilham. A pessoa pode
retirar o consentimento, por campo, a qualquer momento; retirá-lo, desligar as contas ou apagar a conta **remove logo as
cópias publicadas**, no software.

## 7. Informação às pessoas (art. 13.º, 14.º e 26.º, n.º 2)

1. Cada campo informa quem joga no seu aviso de privacidade, secção 2.4, que indica o essencial deste acordo: que o
   campo partilha registos de cronos com outros campos, com o consentimento separado da pessoa, que dados, para quê, e
   que a pessoa pode dirigir-se a qualquer campo participante.
2. O ecrã de consentimento lista os campos que partilham.
3. Cada campo entrega estes termos (ou o essencial deles) a quem os peça.

## 8. Direitos da pessoa

A pessoa pode exercer os seus direitos (acesso, retificação, apagamento, limitação, oposição, retirada do
consentimento) perante **qualquer** campo participante, seja o que for que estes termos digam (art. 26.º, n.º 3). O
campo que recebe um pedido sobre dados partilhados **trata dele ou encaminha-o para o campo certo em 7 dias** e avisa a
pessoa. A retirada do consentimento e o apagamento da conta têm efeito imediato no software. Cada campo responde pelos
pedidos que recebe.

## 9. Segurança

Cada campo mantém seguros os seus dados. Os dados partilhados são guardados pela operação do hub com as medidas de
segurança do acordo de subcontratação: os dados de cada campo no seu esquema de base de dados com segurança ao nível da
linha; os registos de outro campo só acessíveis por uma função de leitura que verifica se os dois campos partilham e se
a pessoa consentiu em ambos; só de leitura para o campo que lê; com registo de auditoria. Um registo leva a sua
assinatura, pelo que o campo que o lê pode verificá-lo sem confiar no servidor.

## 10. Violações de dados pessoais

O campo que descobre uma violação que envolva dados partilhados **avisa os outros campos e a operação do hub em 48
horas**, com o que souber. Cada campo notifica a autoridade de controlo (em Portugal, a CNPD) **quanto aos dados de que
é responsável** em 72 horas (art. 33.º), e as pessoas afetadas quando o artigo 34.º o exija. A operação do hub avisa os
campos de uma violação que descubra em 48 horas (acordo de subcontratação, secção 9).

## 11. Conservação

Uma cópia partilhada só existe enquanto o campo tiver a partilha ligada, o consentimento da pessoa para esse campo
estiver ativo e as contas estiverem ligadas, e acompanha o original: a limpeza diária de conservação faz com que as
cópias publicadas digam de novo o que dizem os registos do próprio campo. A cópia que um campo que lê guarda no seu
controlador é guardada à parte, só para a lista de quem se inscreveu no jogo, no máximo 365 dias, e apagada com o
apagamento da pessoa.

## 12. Saída, e alterações

1. O campo que **desliga a partilha** deixa de ler logo, e as cópias que publicou são apagadas.
2. Quando estes termos mudam, muda a **versão**. Todos os campos são convidados a aceitar a nova versão e, **até o
   fazerem, a sua partilha fica suspensa** (nem publica nem lê; o seu interruptor continua ligado). Os outros campos não
   são afetados.
3. O campo que não aceite a nova versão fica fora da partilha, sem outra consequência.

## 13. Responsabilidade, lei e foro

Perante a pessoa, cada campo responde nos termos da lei (art. 82.º do RGPD; os direitos da pessoa, ao abrigo do
art. 26.º, n.º 3, não são limitados por estes termos); entre os campos, cada um responde pela parte do tratamento que
controla (secção 2). Lei portuguesa; foro de [CIDADE].
