<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Telemóvel como dispositivo de jogo e módulo de E/S

Para quem prepara um telemóvel Android como dispositivo de jogo, com ou sem módulo de E/S. Em inglês: [Phone prop and I/O pod](../en/phone-prop.md).

Um telemóvel que conduz o jogo todo do campo (a função **Controlador de campo**) é outra tarefa: vê o [manual da organização](game-master.md). A própria Field Box está no [Manual de operação da Field Box](field-box.md).

> **Ainda não está pronto para o campo.** A Atalaia está em pré-alfa. O telemóvel como dispositivo de jogo foi testado num computador e no emulador Android da CI. O firmware do módulo de E/S foi testado num computador, com a app e o controlador. **Nenhum dos dois correu num telemóvel ou num módulo a sério num campo.** Os passos que precisam de hardware real dizem **Ainda não experimentado em hardware**.

## Índice

1. [O que é](#1-o-que-é)
2. [Preparar o telemóvel](#2-preparar-o-telemóvel)
3. [Ligar um módulo de E/S](#3-ligar-um-módulo-de-es)
4. [Pôr o telemóvel num jogo](#4-pôr-o-telemóvel-num-jogo)
5. [Durante o jogo](#5-durante-o-jogo)
6. [Quando a ligação ao módulo se perde](#6-quando-a-ligação-ao-módulo-se-perde)
7. [Saídas e módulos no módulo de E/S](#7-saídas-e-módulos-no-módulo-de-es)
8. [Modos que a app não traz](#8-modos-que-a-app-não-traz)
9. [Limites](#9-limites)
10. [Resolução de problemas](#10-resolução-de-problemas)

## 1. O que é

Um **dispositivo de jogo** num telemóvel é um telemóvel Android que faz de caixa: corre o modo de jogo, mostra os ecrãs do modo, tem botões das equipas no ecrã e lê as etiquetas de quem joga com o NFC do telemóvel. Na app é a função **Dispositivo de jogo**. Só o Android o consegue: precisa do modo quiosque, de NFC em segundo plano e de USB.

Um **módulo de E/S** é uma placa pequena (uma Heltec V4, como a de uma caixa) que empresta ao telemóvel o que lhe falta: botões de equipa grandes, um teclado, um anel de luzes, som, um leitor NFC, um rádio LoRa e, opcionalmente, saídas (uma sirene, um estroboscópio...) e uma porta de expansão para um módulo de alvo ou um módulo de saídas. Liga-se ao telemóvel por um **cabo USB-C** (o preferido) ou por **Bluetooth**. Como o montar: [guia de montagem do módulo de E/S](../../../hardware/io-pod/BUILD.pt.md). Como o gravar: [guia do firmware, secção 10](firmware.md#10-as-variantes-do-módulo-de-es).

| | Só o telemóvel | Telemóvel com módulo de E/S |
| --- | --- | --- |
| Botões das equipas | No ecrã | Botões grandes no módulo |
| Etiquetas de quem joga | O NFC do telemóvel | O leitor do módulo |
| Ligação ao controlador | O Wi-Fi do campo | Primeiro o Wi-Fi do campo, o rádio LoRa do módulo enquanto o Wi-Fi está em baixo |
| Saídas, módulo de alvo, módulo de saídas | Nenhum | Se o módulo foi montado com eles ([secção 7](#7-saídas-e-módulos-no-módulo-de-es)) |

## 2. Preparar o telemóvel

Faz isto uma vez, antes do dia de jogo.

1. Instala a app Atalaia e abre-a. Em **O que vais fazer neste telemóvel?**, escolhe **Dispositivo de jogo**.
2. Abre as **Definições** e define:
   - **Chave de entrada do campo**: os 64 algarismos hexadecimais que a organização te dá. Sem ela o telemóvel não entra nos jogos do campo.
   - **PIN da organização**: 4 a 8 algarismos. A app pede-o para começar, pôr em pausa, terminar e sair de um jogo, e para o menu **Organização**. Sem PIN, qualquer pessoa pode pôr em pausa ou terminar um jogo neste dispositivo.
   - **Modo quiosque**: ligado. Durante um jogo o telemóvel fica preso à app; se alguém sair, a app avisa e a organização fica a saber.
   - **Chaves dos modos obtidos**, só se a organização usar modos que a app não traz ([secção 8](#8-modos-que-a-app-não-traz)).
3. Abre **Bateria e segundo plano** (nas **Definições**, ou a partir do aviso no ecrã do dispositivo) e tira a Atalaia da otimização da bateria. O ecrã dá os passos para Samsung, Xiaomi, Huawei, OnePlus e outras marcas. Sem isto, o Android pode parar a app durante um jogo.
4. Carrega o telemóvel. Um jogo de algumas horas com o ecrã ligado gasta muita bateria: leva uma bateria externa.

## 3. Ligar um módulo de E/S

Monta as antenas do módulo antes de o ligares à energia. Nunca ligues um módulo sem a antena LoRa.

**Por USB (o preferido):**

1. Liga o telemóvel ao módulo com um cabo USB-C OTG (um cabo de dados, não um só de carga).
2. Na app, no ecrã do dispositivo, em **Módulo de E/S**, toca em **Ligar um módulo** e depois em **Procurar módulos**.
3. Abre o módulo e autoriza o acesso USB. A app diz **Módulo ligado por USB**.

**Por Bluetooth:**

1. Sem cabo, toca em **Ligar um módulo** e depois em **Procurar módulos**. O módulo aparece como `atalaia-pod-XXXX`. Abre-o.
2. O ecrã pequeno do módulo mostra **PAIR**, os segundos que faltam e um código de 6 algarismos. O Android pede-o: escreve os 6 algarismos em 30 segundos.
3. O módulo mostra **PAIRED** e a app diz **Módulo ligado por BLE**. O telemóvel e o módulo guardam o emparelhamento: fazes isto uma vez.

Se correr mal:

- **Um código errado**, ou *Cancelar*: o módulo mostra **FAILED**. Abre o módulo outra vez para um código novo.
- **Demasiado lento**: o módulo mostra **TOO SLOW**. Abre-o outra vez e escreve o código em 30 segundos.
- **«Este módulo tem de ser emparelhado outra vez»**: o módulo esqueceu os telemóveis, ou foi emparelhado antes de ter código. A app esquece o emparelhamento antigo e volta a abrir o módulo sozinha, uma vez: escreve o código novo. Se o Android não deixar a app esquecê-lo, esquece `atalaia-pod-XXXX` nas definições de Bluetooth do Android e liga-o outra vez.
- **Fazer o módulo esquecer todos os telemóveis**: abre a tampa do módulo e mantém premido o botão **PRG** da placa durante 5 segundos. O módulo mostra **FORGET ALL** e depois **CLEARED**. Faz isto entre jogos: abrir a tampa avisa de uma abertura se o módulo tiver interruptor na caixa.

Um módulo liga-se a um telemóvel de cada vez. O ecrã do módulo só fala inglês. Ainda não experimentado em hardware.

## 4. Pôr o telemóvel num jogo

**Um jogo do controlador de campo (o modo normal):**

1. Toca em **Entrar num jogo**.
2. Lê o **código QR de entrada** na consola da organização, encosta o **cartão de entrada** às costas do telemóvel, ou cola o texto `atalaia:join:...`.
3. O telemóvel mostra **Jogo do controlador**, o número do jogo, o seu número de nó e o canal. Um código de outro campo é recusado (**a chave de entrada não confere**).
4. Espera pelo **Começar** da organização.

O código QR e o cartão de entrada levam a chave do jogo: mostra-os só a quem está a preparar o campo.

**Um jogo só neste telemóvel:** toca em **Novo jogo**, escolhe o modo, a função, as equipas, os parâmetros e a duração, e depois **Preparar o jogo** e **Começar**. Um modo que conta pontos com várias caixas precisa do controlador: sozinho, o dispositivo só faz a parte dele, e a app di-lo. Se o modo precisar de algo que o telemóvel não tem (um leitor NFC, por exemplo), a app diz o quê: liga um módulo de E/S que o tenha.

## 5. Durante o jogo

- O telemóvel mostra o ecrã do modo, com botões **Manter premido** para cada equipa, ou usa os botões do módulo. As etiquetas de quem joga encostam-se às costas do telemóvel, ou ao leitor do módulo.
- **Organização** (no ecrã do jogo) pede o PIN da organização e abre um menu: **Pausa** / **Retomar** e **Terminar o jogo** (quando se aplicam), **Ligar o módulo outra vez** e **Desligar o módulo de E/S** (com módulo), **Registo do jogo** e **Sair**.
- **Sair** tira este dispositivo de um jogo que ainda decorre: **Sair do jogo?** O jogo continua para toda a gente, e este dispositivo deixa de contar. Não é o **Sair do jogo** da app de quem joga (que apaga o nome da pessoa do jogo), nem a entrada com o mesmo nome no menu de administração da Field Box ([manual da Field Box](field-box.md#take-a-box-out-of-its-game)).
- Uma faixa vermelha diz **Alguém saiu do modo quiosque durante o jogo** ou **Alguém abriu o módulo de E/S durante o jogo**. A organização também fica a saber. Avisa a organização.
- Mantém a app em primeiro plano. Se o Android a mandar para segundo plano, as saídas do módulo desligam-se ([secção 7](#7-saídas-e-módulos-no-módulo-de-es)).

## 6. Quando a ligação ao módulo se perde

1. A app volta a abrir a ligação sozinha, e o ecrã do jogo diz isso: **A ligação ao módulo de E/S perdeu-se. A religar (tentativa N)…**. Um módulo que tenha de ser emparelhado outra vez é emparelhado mais uma vez, e o ecrã pede o código novo.
2. Se não resultar (um código de emparelhamento errado ou lento, um módulo que recusa o telemóvel), uma faixa vermelha diz **A app não conseguiu voltar a ligar o módulo sozinha** e porquê. Se respondeu outro módulo, a faixa indica o módulo que o jogo espera.
3. Traz esse módulo. Toca em **Organização**, escreve o PIN da organização e toca em **Ligar o módulo outra vez**. A app tenta o módulo de imediato; o Android pede o código do ecrã do módulo se tiver de emparelhar.
4. Quando o módulo volta, a faixa desaparece e o jogo continua com o módulo (os botões, as saídas e o rádio), sem recomeçar. Se falhar outra vez, a faixa volta com o motivo novo.

Entretanto o jogo continua sem o módulo. Depois do jogo, também podes ligar um módulo no ecrã do dispositivo (**Módulo de E/S**). Ainda não experimentado em hardware.

## 7. Saídas e módulos no módulo de E/S

**Saídas simples.** Um módulo de E/S montado com uma **saída simples** (uma sirene, um estroboscópio, uma luz ou o comando de uma máquina de fumo num interruptor de relé RC; [guia de montagem do módulo de E/S, secção 8.1](../../../hardware/io-pod/BUILD.pt.md#81-saídas-simples-opcionais)) empresta-a ao telemóvel. O jogo no telemóvel liga-a como uma caixa liga a sua, e a organização também, na consola.

- Não há nada a ativar no telemóvel nem no módulo: um módulo de E/S não tem PIN de administração, por isso quem o montou definiu o uso da saída (**siren**, **smoke**...) e o tempo máximo ligada ao compilá-lo. Pergunta a quem o montou que uso tem: o jogo pede uma saída pelo seu uso.
- As mesmas regras de uma caixa ([manual da Field Box, secção 8.1](field-box.md#81-o-que-o-jogo-faz-com-uma-saída)): só durante o jogo (e uma buzina de fim de jogo até 10 segundos), desligada quando o jogo começa, fica em pausa ou acaba, nunca mais tempo do que o seu máximo, no máximo uma mudança a cada meio segundo.
- **Se o telemóvel se vai, a saída desliga-se.** O módulo desliga-a quando o cabo USB sai, a ligação Bluetooth cai ou a app deixa de lhe falar durante 1,5 segundos.

**Um módulo de alvo ou um módulo de saídas.** Um módulo de E/S com porta de expansão aceita os mesmos módulos de uma caixa ([guia de montagem do módulo de E/S, secção 8.2](../../../hardware/io-pod/BUILD.pt.md#82-porta-de-expansão-opcional)):

- **Um módulo de alvo**: liga-o e o jogo no telemóvel conta os impactos enquanto o jogo decorre, como numa caixa.
- **Um módulo de saídas**: os relés dele funcionam como as saídas simples do módulo de E/S, só se este foi compilado para os emprestar. O tempo máximo é o da compilação do módulo de E/S, nunca mais do que o do próprio módulo de saídas. O módulo de E/S desliga-os quando o telemóvel se vai.
- Liga os módulos antes do jogo. A organização vê-os debaixo do telemóvel na consola.

**A segurança** é a da caixa: só aparelhos de baixa tensão com bateria ou alimentação própria (no máximo 24 V), nunca a rede elétrica, uma máquina de fumo só pela sua entrada de comando de baixa tensão, nunca pirotecnia, proteção auditiva perto de sirenes, proteção dos olhos e da cara perto de um alvo ([manual da Field Box, secção 8.5](field-box.md#85-segurança)).

Ainda não experimentado em hardware.

## 8. Modos que a app não traz

Se o jogo usa um modo que a app não traz, e a organização o permitir, o telemóvel obtém o modo do controlador do campo, pelo Wi-Fi do campo, antes de o jogo começar. Só aceita um pacote **assinado** por uma chave de modo em que confias:

1. Pede a chave de modo à organização: a do projeto ou a do teu clube.
2. Em **Definições › Chaves dos modos obtidos**, cola-a (44 caracteres base64; uma por linha, no máximo 4). Nunca acrescentes uma chave que não te tenha sido dada pelo projeto ou pelo teu clube.
3. Liga-te ao Wi-Fi do campo e entra no jogo. A app diz **A obter o modo do jogo do controlador e a verificar a assinatura…**.

Um pacote sem assinatura, assinado por outra chave ou danificado é recusado com uma mensagem e nunca é executado. Sem nenhuma chave de modo, o telemóvel só corre os modos incluídos na app. Ainda não testado num campo.

## 9. Limites

- **Só Android.** Um iPhone não pode ser dispositivo de jogo.
- **Um telemóvel por módulo de E/S**, e um módulo por telemóvel, de cada vez.
- **O módulo de E/S não tem PIN de administração.** As saídas dele estão como quem o montou as compilou; o PIN da organização no telemóvel protege o jogo.
- **O telemóvel tem de ficar acordado e à frente.** Otimização da bateria desligada, a app em primeiro plano; caso contrário o jogo deixa de contar ou as saídas do módulo desligam-se.
- **Um módulo de E/S não é um modem de rádio para os avisos de caixas presas do controlador.** Um telemóvel controlador que usa um módulo de E/S como rádio não consegue libertar sozinho caixas presas num jogo terminado: vê o [manual da Field Box](field-box.md#take-a-box-out-of-its-game).
- O módulo de E/S e os módulos da porta gravam-se outra vez por USB, nunca se atualizam pelo ar.
- Nada disto foi usado num campo a sério.

## 10. Resolução de problemas

| Problema | O que fazer |
| --- | --- |
| **Primeiro define a chave de entrada do campo nas definições.** | Define a **Chave de entrada do campo** nas **Definições** ([secção 2](#2-preparar-o-telemóvel)). |
| O código de entrada é recusado: de outro campo | A chave de entrada do telemóvel não é a deste campo. Pede a chave certa à organização. |
| **Este código é para um controlador de reserva, não para um dispositivo.** | A organização mostrou o código errado. Pede o código de entrada para dispositivos. |
| O telemóvel não encontra o módulo por USB | Um cabo só de carga, ou um telemóvel sem USB anfitrião (OTG). Experimenta outro cabo. |
| `atalaia-pod-XXXX` não aparece | Falta a antena de 2,4 GHz do módulo, outro telemóvel está ligado (um de cada vez), ou o módulo foi compilado sem Bluetooth. |
| O Android pede um código mas o ecrã do módulo fica apagado | O ecrã pequeno do módulo não foi encontrado no arranque. Fala com quem o montou (o código está no registo do módulo). |
| **Este módulo tem de ser emparelhado outra vez** sempre | O Android não esqueceu o emparelhamento: esquece `atalaia-pod-XXXX` nas definições de Bluetooth e liga-o outra vez. |
| **Falta a este telemóvel: …** | O modo precisa de uma peça que o telemóvel não tem. Liga um módulo de E/S que a tenha. |
| A sirene do módulo de E/S nunca liga | O módulo foi compilado sem a saída, ou com um uso diferente do que o jogo pede (fala com quem o montou); o módulo não está ligado; nenhum jogo a decorrer; a bateria do próprio interruptor está vazia. |
| A saída do módulo de E/S desliga-se sozinha | O telemóvel deixou de falar com o módulo (a app foi para segundo plano ou foi fechada) ou a ligação caiu. Liga de novo; mantém a app em primeiro plano. |
| Os impactos do alvo nunca chegam ao jogo | O jogo não está a decorrer, ou a app é mais antiga do que o módulo. Atualiza a app. |
| **Este dispositivo não confia em nenhuma chave de modo, por isso não aceita modos do controlador.** | Acrescenta a chave de modo em **Definições › Chaves dos modos obtidos** ([secção 8](#8-modos-que-a-app-não-traz)). |
| **Não foi possível chegar ao controlador com o certificado do campo.** | Liga-te ao Wi-Fi do campo e tenta outra vez. |
| O jogo deixou de contar quando o ecrã se apagou | Tira a Atalaia da otimização da bateria (**Bateria e segundo plano**). |

Para as avarias de montagem e de bancada do módulo, vê o [guia de montagem do módulo de E/S, secção 11](../../../hardware/io-pod/BUILD.pt.md#11-resolução-de-problemas).
