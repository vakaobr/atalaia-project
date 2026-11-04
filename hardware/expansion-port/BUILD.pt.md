<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Guia de montagem da porta de expansão

Em inglês: [Expansion port build guide](BUILD.md).

Como equipar uma caixa com a **porta de expansão**: a tomada M12 de 5 pinos,
estanque, onde se ligam módulos vindos de fora (o
[módulo de alvo](../target-addon/BUILD.pt.md) agora, contactos e outros
sensores mais tarde), e a pequena **placa da porta** atrás dela, que impede
que um cabo molhado, em curto-circuito ou carregado de eletricidade estática
deite a caixa abaixo. Escrito para alguém do clube que saiba soldar pinos e
fios e usar um multímetro, como o
[manual de montagem da Field Box](../field-box/BUILD.pt.md), que este guia
segue e para o qual remete em todos os passos que as montagens partilham.

> **Estado: desenhada, ainda não montada.** A porta, a sua pinagem, a sua
> proteção e os seus endereços estão decididos (rascunho do RFC «The expansion
> port», [`docs/rfcs/0000-expansion-port.md`](../../docs/rfcs/0000-expansion-port.md),
> decisões EXP-1 a EXP-15, aprovadas por quem mantém o projeto em
> 2026-11-03); o protocolo de registos que os módulos falam está em
> [`protocol/expansion-port.md`](../../protocol/expansion-port.md). **Ainda
> não se montou nenhuma porta a partir deste guia**, e **o firmware da caixa
> ainda não usa a porta**: o controlador da porta está a ser escrito
> (`firmware/esp32/main/expansion.c`, incremento 6 do plano do RFC) e só é
> chamado pela tarefa de jogo da caixa a partir do **incremento 8**. Até lá,
> uma porta pode ser montada e verificada com um multímetro e com as peças da
> própria caixa ([secção 8](#8-verificações-e-testes)), mas nenhum módulo
> responde. A tabela de pinos é verificada automaticamente contra as
> predefinições do firmware (`python3 tools/check_wiring.py`). Os passos
> marcados **Verifica na primeira montagem** são questões em aberto; conta o
> que encontrares numa issue. As fotografias serão juntadas depois da primeira
> montagem (fase HW2 do plano); este guia nunca usa fotografias de maquetas
> nem geradas.

**Não é para saídas, por regra.** Uma sirene, um estroboscópio ou o comando
de uma máquina de fumo usam a **saída simples** (um GPIO, um interruptor de
relé RC, uma tomada M8:
[manual da Field Box, secção 9.10](../field-box/BUILD.pt.md#910-saída-simples-opcional)),
o caminho preferido para saídas (EXP-31). A porta é para **entradas** e, mais
tarde, para um módulo de saídas I2C numa caixa que precise de mais canais ou
de confirmação.

## Índice

1. [O que estás a montar](#1-o-que-estás-a-montar)
2. [O que está decidido e o que não está](#2-o-que-está-decidido-e-o-que-não-está)
3. [Peças, e contra o que protege cada uma](#3-peças-e-contra-o-que-protege-cada-uma)
4. [Ferramentas e segurança](#4-ferramentas-e-segurança)
5. [Os pinos da porta](#5-os-pinos-da-porta)
6. [Endereços no barramento](#6-endereços-no-barramento)
7. [Montagem, passo a passo](#7-montagem-passo-a-passo)
8. [Verificações e testes](#8-verificações-e-testes)
9. [Resolução de problemas](#9-resolução-de-problemas)

## 1. O que estás a montar

A porta é o próprio barramento I2C da caixa (o do expansor do teclado, do
leitor NFC, do medidor de bateria e do OLED da placa, nos GPIO 17 e 18) levado
para fora do invólucro por uma tomada M12. **Não usa nenhum GPIO**, por isso a
tabela de pinos de nenhuma caixa muda (EXP-2). Entre o barramento e a tomada
fica a placa da porta:

```
barramento I2C da caixa (placa de interligação)   placa da porta                       tomada M12 (de painel)
  3V3 ──── díodo Schottky ── fusível PTC 50 mA ──────────────┬── TVS (VBUS) ──── pino 1  3,3 V (cerca de 3,0 V)
  SDA ──── buffer SDAIN │ SDAOUT ── 2,2 kohm aos 3,3 V da porta ┴─ 100 ohm ── TVS ── pino 2  SDA
  SCL ──── buffer SCLIN │ SCLOUT ── 2,2 kohm aos 3,3 V da porta ── 100 ohm ── TVS ── pino 4  SCL
  GND ──────────────────┴──────────────────────────────────────────── GND do TVS ── pino 3  GND
                                                                                   pino 5  não ligado
```

- O **buffer de ligação a quente** (TCA4307) junta a porta ao barramento da
  caixa só quando os dois estão parados, e desliga a porta quando alguma coisa
  no cabo segura SDA ou SCL em baixo, enviando impulsos de relógio para soltar
  o módulo encravado. O teclado, o leitor NFC, o medidor e o OLED da caixa
  continuam a funcionar.
- A **matriz TVS** e as **resistências de 100 ohm em série** recebem a
  eletricidade estática de uma mão ou de um cabo, na tomada.
- O **fusível PTC** limita um curto-circuito entre os pinos 1 e 3; o **díodo
  Schottky** impede que alguma coisa no cabo alimente o trilho de 3,3 V da
  caixa ao contrário.

Montada na **Field Box, no Satélite e no módulo de E/S**, sempre opcional: só
uma caixa que leve um alvo ou um sensor precisa dela (EXP-2). Custo
aproximado: tomada 3-6 €, buffer 2-6 € (uma placa de breakout), TVS, fusível,
díodo e resistências 1-2 €, mais uma placa perfurada e fio (RFC, secção 1;
preços do mercado de amadores, não é um orçamento).

## 2. O que está decidido e o que não está

Decidido (com a origem de cada decisão):

| O quê | Decidido | Onde |
| --- | --- | --- |
| Conector | M12 de codificação A, 5 pinos (IEC 61076-2-101). Pinagem: 1 castanho 3,3 V, 2 branco SDA, 3 azul GND, 4 preto SCL, 5 cinzento reservado, **não ligado** | EXP-1; P5J-20 |
| Género da tomada | Uma tomada de painel **fêmea** na caixa (os contactos ficam recolhidos, e o pino 1 tem tensão); um conector de painel macho no módulo; entre os dois, um cabo de extensão de sensor M12 de codificação A, 5 polos, **macho-fêmea**, já feito | Este guia (EXPI10-2) |
| Alimentação | 3,3 V só para a **lógica** de um módulo, no máximo **25 mA**; as cargas nunca tiram energia da caixa | EXP-3; P5J-16 |
| Proteção | Buffer de ligação a quente com recuperação de barramento encravado, matriz TVS de baixa capacidade, resistências de 100 ohm em série, fusível PTC (cerca de 50 mA de retenção), díodo Schottky contra a alimentação inversa; resistências de pull-up de 2,2 kohm do lado da porta | EXP-4 |
| Peças exatas | Buffer TCA4307, uma matriz TVS da classe USBLC6-2SC6, um PTC radial de 50 mA de retenção, um díodo Schottky da classe BAT85 ([secção 3](#3-peças-e-contra-o-que-protege-cada-uma)) | Este guia (EXPI10-3 a EXPI10-6) |
| Barramento | I2C a **100 kHz** (definido pelo PN532), por consulta, sem linha de interrupção | EXP-5, EXP-6, EXP-8; P5J-17, P5J-18 |
| Cabo | No máximo **2 m** de cabo de sensor M12 de 5 condutores. Mais longe: um Satélite junto ao alvo | EXP-5; P5J-17 |
| Pull-ups nos módulos | **Nenhum.** A placa da porta tem-nos | EXP-4; P5J-17 |
| Endereços | Os módulos respondem em **0x58-0x5F**; as entradas (o módulo de alvo) começam em 0x58, as saídas em 0x5C; no máximo 4 módulos numa caixa | EXP-7 ([secção 6](#6-endereços-no-barramento)) |
| O que se pode ligar | Módulos com um processador que fale o protocolo de expansão v1. **Não** placas de relés PCF8574 ou MCP23017 simples | EXP-9, EXP-15 |

Não decidido, ou ainda não feito:

- **O firmware da caixa para a porta** (incrementos 6 e 8 do plano do RFC):
  até ao incremento 8 a caixa não procura módulos, por isso nada do que se
  ligue é lido.
- **Uma placa de circuito impresso** com a placa da porta (a placa de suporte
  posterior da fase 5); até lá, placa perfurada.
- **Os resultados de bancada** da [secção 8](#8-verificações-e-testes): tempos
  de subida, a recuperação do buffer, o fusível, a estática, a ligação a
  quente. Os valores que a primeira montagem pode mudar estão marcados
  **Verifica na primeira montagem**.
- **Um diagrama de ligações**: a porta ainda não está nos diagramas WireViz da
  Field Box; pode vir depois da primeira montagem.

## 3. Peças, e contra o que protege cada uma

Um conjunto por porta. Cada peça tem o tipo e um exemplo de referência que
serve; uma equivalente com as mesmas características também serve.

| # | Peça | Qtd | Para que serve, e contra o que protege | O que verificar |
| --- | --- | --- | --- | --- |
| 1 | Tomada de painel M12 de codificação A, 5 pinos, **fêmea**, IP67, de montagem frontal, com fios já soldados ou copos de solda | 1 | A própria porta. Um conector estanque e com chave: a codificação A impede que um cabo entre rodado | **Codificação A**, **5 pinos** (não 4, não 8, nem codificação B ou D); IP67 com a tampa e quando ligada. A rosca (muitas vezes PG9 ou M16) dá o tamanho do furo |
| 2 | Tampa de proteção da tomada, presa por um cordão | 1 | Impede a entrada de água e terra enquanto nada está ligado | Serve na rosca da tomada |
| 3 | Cabo de extensão de sensor M12 de codificação A, 5 polos, **macho-fêmea**, 1-2 m | 1 por módulo | Leva o barramento até ao módulo. As cores habituais condizem com a pinagem (castanho, branco, azul, preto, cinzento) | **Não precisa de blindagem**; confirma as cores com um multímetro (pino a fio) antes de confiar nelas |
| 4 | Buffer I2C de ligação a quente **TCA4307**, com recuperação de barramento encravado, numa placa de breakout | 1 | **Um cabo em curto ou molhado a segurar SDA ou SCL em baixo** pararia o teclado, o leitor NFC, o medidor e o OLED: o buffer liga a porta só quando os dois lados estão parados, desliga-a quando uma linha da porta fica em baixo (cerca de 30 ms), e envia impulsos de relógio para soltar o módulo encravado. Também tira a capacidade do cabo do barramento da caixa | As etiquetas: VCC, GND, SDAIN, SCLIN, SDAOUT, SCLOUT, EN, READY. Toma nota das resistências de pull-up na placa de breakout ([passo 3](#7-montagem-passo-a-passo)). O LTC4307 faz o mesmo trabalho; os pinos são outros |
| 5 | Matriz TVS (ESD) de baixa capacidade com um pino para o trilho de alimentação, da classe **USBLC6-2SC6** (SOT-23-6), num adaptador de SOT-23-6 para DIP | 1 | **Eletricidade estática de uma mão, ou de um cabo a roçar na roupa**, na tomada: limita SDA, SCL e os 3,3 V do pino 1 ao GND antes de a descarga chegar ao buffer | Tensão de trabalho de pelo menos 3,3 V e no máximo 5,5 V; poucos pF por linha (um TVS de potência de furo passante, com vários nF, tornaria o barramento lento) |
| 6 | Resistências de 100 ohm, 1/4 W | 2 | Com o TVS: **limitam a corrente de uma descarga de estática** para os pinos do lado da porta do buffer, em SDA e SCL | |
| 7 | Resistências de 2,2 kohm, 1/4 W | 2 | As **pull-ups** do lado da porta, aos 3,3 V da porta; os módulos não têm nenhuma | Menos se a placa de breakout já tiver pull-ups do lado OUT ([passo 3](#7-montagem-passo-a-passo)) |
| 8 | Fusível rearmável (PTC), **50 mA de retenção**, radial (classe MF-R005) | 1 | **Um curto-circuito entre os pinos 1 e 3** (um cabo esmagado, água na ficha): aquece e limita a corrente, para a caixa não ir abaixo, e rearma quando o curto desaparece | Corrente de retenção cerca de 50 mA (disparo cerca de 100 mA), para pelo menos 6 V |
| 9 | Díodo Schottky pequeno, da classe **BAT85** (ou 1N5817) | 1 | **Alguma coisa no cabo a alimentar o pino 1** (um módulo mal ligado com alimentação própria): nada pode alimentar o trilho de 3,3 V da caixa ao contrário. O módulo vê cerca de 3,0 V | Tensão direta baixa (cerca de 0,3 V a 25 mA) |
| 10 | Condensador cerâmico de 100 nF | 1 | Desacopla o VCC do buffer | Muitas vezes já está na placa de breakout |
| 11 | Placa perfurada de cerca de 3 x 4 cm, pinos, fio multifilar de 0,25 mm² nas cores abaixo, manga termorretrátil | 1 conjunto | A placa da porta, ligada aos trilhos da placa de interligação | |
| 12 | Etiqueta «EXPANSÃO 3,3 V» | 1 | Diz o que é a tomada | Para não confundir com a tomada M8 «SAÍDA 1» da saída simples |

## 4. Ferramentas e segurança

As ferramentas são as da Field Box ([manual, secção 3](../field-box/BUILD.pt.md#3-ferramentas-e-consumíveis)),
mais um ferro de ponta fina para o adaptador SOT-23-6 (ou compra o TVS já
soldado num). Lê as [regras de segurança](../field-box/BUILD.pt.md#4-regras-de-segurança)
do manual; aplicam-se todas. Para a porta em particular:

1. **Bateria fora, fusível fora, interruptor desligado, USB desligado**
   enquanto soldas ou ligas a placa da porta.
2. **Só 3,3 V, em todos os pinos, sempre.** A porta é o barramento de 3,3 V
   da caixa: sem 5 V, sem a tensão da bateria, e nada da alimentação própria
   de um módulo chega lá (EXP-3, P5J-15). Um módulo que puxe SDA ou SCL acima
   de 3,3 V pode estragar a placa da caixa.
3. **O pino 5 fica sem ligação** nas duas pontas: nunca alimentação, nunca
   sinal (EXP-1).
4. **Nunca alimentes uma carga a partir da porta.** Os seus 25 mA são para o
   processador e o sensor de um módulo. Luzes, relés, sirenes e máquinas de
   fumo trazem a sua própria alimentação; um único LED WS2812 já gasta até
   60 mA.
5. **Nunca ligues à porta uma placa de relés PCF8574 ou MCP23017 simples (nem
   nenhuma «placa de relés I2C» sem processador próprio).** Não tem
   concessão, por isso um relé fica ligado se a caixa encravar; responde onde
   a caixa procura o expansor do teclado, por isso uma caixa sem teclado
   faria os relés estalar a cada 10 ms; os relés podem ligar-se todos ao
   arrancar; e as bobinas funcionariam com os 3,3 V da porta (EXP-15).
6. **Nunca a rede elétrica.** Nada de nenhum dos lados da porta toca em
   ligações à rede elétrica (EXP-17).
7. **Estática.** Toca no GND da caixa (ou usa uma pulseira) antes de mexeres
   na placa da porta, e antes de ligares um módulo na bancada.
8. **Tapa a tomada** quando nada estiver ligado; a porta só é estanque tapada
   ou ligada. Passa o cabo pelo chão longe dos pés dos jogadores e **nunca na
   linha de fogo**: só se dispara para a placa de um alvo.
9. **Um adereço de jogo**: a caixa mantém a cor viva e as etiquetas «GAME
   PROP».

## 5. Os pinos da porta

A porta não usa nenhum GPIO próprio: o seu SDA e o seu SCL são o barramento
I2C da caixa, atrás do buffer. Os números de GPIO são as predefinições em
[`firmware/esp32/main/Kconfig.projbuild`](../../firmware/esp32/main/Kconfig.projbuild);
`python3 tools/check_wiring.py` falha se esta tabela não condisser com elas ou
com a pinagem da EXP-1 (a cor, o sinal e o número de cada pino, os GPIO e as
opções do barramento, nada no pino 5).

<!-- check_wiring: expansion-port-pins -->
| Pino M12 | Cor do fio | Sinal | GPIO do barramento | Opção do firmware | Na placa da porta | Nível |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | castanho | 3,3 V | -- | -- | trilho 3V3 da placa de interligação, díodo Schottky (risca virada para a porta), fusível PTC, pino VBUS do TVS, pino 1 da tomada | cerca de 3,0 V, no máximo 25 mA |
| 2 | branco | SDA | 17 | `ATALAIA_NFC_SDA_PIN` | trilho SDA ao SDAIN do buffer; SDAOUT com 2,2 kohm aos 3,3 V da porta, depois 100 ohm e uma linha do TVS até ao pino 2 da tomada | 3,3 V, 100 kHz |
| 3 | azul | GND | -- | -- | trilho GND, o GND do buffer, o GND do TVS, pino 3 da tomada | 0 V |
| 4 | preto | SCL | 18 | `ATALAIA_NFC_SCL_PIN` | trilho SCL ao SCLIN do buffer; SCLOUT com 2,2 kohm aos 3,3 V da porta, depois 100 ohm e uma linha do TVS até ao pino 4 da tomada | 3,3 V |
| 5 | cinzento | não ligado | -- | -- | nada: corta o fio curto e isola-o | reservado |

Num Satélite, a opção do mesmo barramento chama-se `ATALAIA_BATT_SDA_PIN` /
`ATALAIA_BATT_SCL_PIN` (o nome que o medidor lhe dá): os mesmos GPIO 17 e 18.

**Os pinos do próprio buffer:** VCC ao trilho 3V3 da placa de interligação (o
lado da caixa, antes do díodo), GND ao trilho GND, **EN ao VCC** (sempre
ativo; a porta não tem nenhum GPIO para o comandar), READY sem ligação.

SDA e SCL estão nos pinos 2 e 4, em lados opostos do conector em vez de lado a
lado (P5J-20). Olhando de fora para a tomada fêmea da caixa, os pinos 1-4
estão à volta do bordo e o pino 5 ao centro; confirma os números na folha de
características da tua tomada antes de soldar.

## 6. Endereços no barramento

Cada módulo responde num endereço próprio em **0x58-0x5F** (EXP-7), longe de
todos os endereços que a caixa usa ou procura:

| Endereço | O quê | Notas |
| --- | --- | --- |
| 0x00-0x07, 0x78-0x7F | Gamas reservadas do I2C | Nunca usadas |
| 0x20-0x27, 0x38-0x3F | Onde a caixa procura o expansor do teclado (PCF8574 / PCF8574A) | A razão por que as placas de relés PCF8574 simples são recusadas (EXP-15) |
| 0x24 | Leitor NFC PN532 | Dentro de 0x20-0x27: a procura do teclado salta-o |
| 0x36 | Medidor de bateria MAX17048 | |
| 0x3C | O OLED da placa | |
| **0x58-0x5B** | **Módulos de entrada**: o módulo de alvo em **0x58**; os seus dois jumpers de solda somam 1-3 para um segundo, terceiro ou quarto | |
| **0x5C-0x5F** | **Módulos de saída** (o futuro módulo de saídas I2C) em **0x5C**, jumpers 0x5D-0x5F | |

**No máximo 4 módulos numa caixa**: o tempo do barramento (a consulta de cada
módulo de entrada ocupa cerca de 5 % do barramento) e os 25 mA que cada um
tira do mesmo trilho de 3,3 V são os limites. A porta leva **um cabo**: mais
de um módulo numa caixa precisa de um repartidor, que **ainda não está
desenhado**; este guia monta um módulo por caixa.

## 7. Montagem, passo a passo

<!-- PHOTO: expansion-port-board.jpg | the finished port board, both sides, with the buffer breakout, the TVS on its adapter, the fuse and the diode -->
> **Fotografia a juntar depois da primeira montagem:** a placa da porta
> acabada, dos dois lados.

1. **Onde fica a tomada.** Num lado ou no fundo do invólucro, longe das
   antenas e da tomada M8 da saída simples, onde um cabo vindo do chão entre
   sem uma curva apertada, e **não virada para quem dispara** quando a caixa
   está no campo. Faz o furo que a folha de características indica (muitas
   vezes PG9 ou M16), tira as rebarbas, monta a tomada com o O-ring do lado de
   fora e aperta a porca à mão mais um quarto de volta. Prende o cordão da
   tampa.
2. **Disposição da placa da porta.** Numa placa perfurada de cerca de
   3 x 4 cm: uma barra de 4 pinos «BUS IN» (3V3, GND, SDA, SCL) num bordo, a
   placa de breakout do buffer, o TVS no seu adaptador tão perto quanto
   possível de uma barra de 5 pinos «SOCKET» no outro bordo, e entre eles o
   díodo, o fusível, as duas resistências de 100 ohm e as duas de 2,2 kohm.
   Mantém o lado «BUS IN» e o lado «SOCKET» afastados: o buffer fica entre
   eles.
3. **As resistências da própria placa de breakout.** Muitas placas de
   breakout do TCA4307 trazem pull-ups (muitas vezes de 10 kohm) num dos lados
   ou nos dois. Com a placa sem alimentação, mede SDAIN a VCC, SCLIN a VCC,
   SDAOUT a VCC e SCLOUT a VCC. Pull-ups do lado **IN** somam-se às do
   barramento da caixa: o barramento da caixa tem de continuar a medir entre
   **1 kohm e 3,9 kohm** ao 3V3 com todas as peças da caixa montadas (P5J-17:
   flancos suficientemente rápidos, e menos de 3 mA para uma peça puxar a
   linha para baixo). Do lado **OUT** a porta quer cerca de **2,2 kohm no
   total**: se a placa de breakout já tiver as suas desse lado, escolhe a
   resistência a juntar para que as duas em paralelo deem cerca de 2,2 kohm,
   ou corta o jumper da placa, se tiver um. Anota o que encontraste na issue
   da tua montagem.
4. **Caminho da alimentação.** 3V3 da placa de interligação ao 3V3 de «BUS
   IN», ao VCC do buffer (com os 100 nF ao GND se a placa de breakout não os
   tiver) e ao **ânodo** do díodo; o **cátodo** do díodo (a risca) ao fusível;
   a outra perna do fusível é o nó dos **3,3 V da porta**: ao pino VBUS do
   TVS, às duas resistências de 2,2 kohm e ao pino 1 de «SOCKET». O **EN** do
   buffer ao seu VCC.
5. **Sinais.** SDA de «BUS IN» ao SDAIN, SCL ao SCLIN. SDAOUT a uma 2,2 kohm
   (aos 3,3 V da porta) e a uma 100 ohm; a outra ponta da 100 ohm a uma linha
   de E/S do TVS e ao pino 2 de «SOCKET». O mesmo para SCLOUT, a segunda
   2,2 kohm e 100 ohm, a outra linha de E/S do TVS e o pino 4 de «SOCKET».
   Num USBLC6-2SC6 cada linha tem dois pinos (1 e 6 são a E/S 1, 3 e 4 a
   E/S 2): junta cada par, como mostra a folha de características.
6. **Massa.** GND de «BUS IN» ao GND do buffer, ao pino GND do TVS e ao pino 3
   de «SOCKET», com fios curtos e diretos: o TVS só é tão bom quanto o seu
   caminho para o GND.
7. **Fios da tomada.** Da barra «SOCKET» aos pinos da tomada, com menos de
   10 cm, nas cores do cabo: pino 1 castanho, 2 branco, 3 azul, 4 preto. **O
   fio do pino 5 é cortado curto e isolado** com manga termorretrátil: não vai
   a lado nenhum. Manga termorretrátil em todos os copos de solda.
8. **À caixa.** Quatro fios, com menos de 15 cm, de «BUS IN» aos trilhos 3V3,
   GND, SDA e SCL da placa de interligação
   ([manual da Field Box, secção 8](../field-box/BUILD.pt.md#8-a-placa-de-interligação);
   o Satélite e o módulo de E/S têm os mesmos trilhos). Fixa a placa da porta
   em espaçadores ou com fita de espuma de dupla face, longe dos fios de 5 V e
   da bateria, e prende os fios para nada puxar uma solda.
9. **Etiqueta** a tomada por fora: «EXPANSÃO 3,3 V».

## 8. Verificações e testes

### 8.1 Antes de qualquer energia (multímetro, bateria fora, USB desligado)

- [ ] Pino 1 ao pino 3 da tomada: **sem continuidade** (uma leitura de alguns
      kohm é o TVS e as pull-ups; um apito é um curto-circuito).
- [ ] Pino 5 da tomada a todos os outros pinos e às partes metálicas do
      invólucro: **aberto**.
- [ ] Teste de díodo do 3V3 da placa de interligação (ponta vermelha) à perna
      do fusível do lado do díodo: cerca de 0,2-0,4 V; ao contrário: aberto. A
      risca aponta para a porta.
- [ ] Pino 2 da tomada ao SDAOUT e pino 4 ao SCLOUT: cerca de **100 ohm**
      cada.
- [ ] SDAOUT e SCLOUT ao nó dos 3,3 V da porta: cerca de **2,2 kohm** cada
      (incluindo as da placa de breakout).
- [ ] SDA ao 3V3 e SCL ao 3V3 da placa de interligação: entre **1 kohm e
      3,9 kohm**, com todos os módulos da caixa montados
      ([passo 3](#7-montagem-passo-a-passo)).
- [ ] Sem continuidade de nenhum pino da tomada ao trilho de 5 V ou ao BAT+.

### 8.2 Primeira energia, nada ligado

1. Alimenta a caixa por USB (interruptor desligado, como no
   [manual da Field Box, secção 10](../field-box/BUILD.pt.md#10-primeira-ligação-à-energia)).
   Mede o pino 1 ao pino 3 da tomada: cerca de **3,0 V** (o trilho de 3,3 V
   menos o díodo). Pinos 2 e 4 ao pino 3: o mesmo, em alto em repouso.
2. A caixa arranca como antes; na
   [lista de verificação de bring-up](../../firmware/esp32/docs/BRING_UP.md)
   o teclado (passo 5), o leitor NFC (passo 7) e o medidor (passo 9)
   continuam a funcionar. Repete com o cabo de 2 m ligado à tomada e nada na
   outra ponta.

### 8.3 Testes de bancada

A lista de bancada do RFC (secção 7, «Bench tests»), para a porta; cada um
precisa do firmware da caixa e, onde se diz, de um módulo. Conta os
resultados numa issue: são eles que resolvem os itens **Verificar na primeira
montagem**.

| Teste do RFC | O quê | Precisa de | Quando |
| --- | --- | --- | --- |
| 1 | Tempo de subida de SDA e SCL na outra ponta do cabo, 2 m de cabo, 100 kHz: **menos de 1 µs** (um osciloscópio). A estimativa: 2,2 kohm e cerca de 250 pF dão cerca de 0,5 µs. O teclado, o leitor NFC e o medidor continuam a funcionar com um módulo ligado | Osciloscópio; um módulo para a segunda parte | Tempo de subida: já. Com um módulo: **depois do incremento 8** |
| 2 | Curto-circuito de SDA ao GND na outra ponta do cabo: o teclado da caixa continua a funcionar; a porta volta menos de um segundo depois de tirar o curto | O firmware da caixa (o teclado) | Já (o teclado); o módulo a voltar: **depois do incremento 8** |
| 4 | Curto-circuito dos pinos 1 e 3 na outra ponta do cabo: a caixa não reinicia; o fusível aquece e recupera quando o curto desaparece. A corrente do módulo de alvo abaixo de 25 mA | Um módulo para a corrente | O curto: já. A corrente do módulo: **depois do incremento 8** |
| 9 | Tocar nos pinos da tomada e na carcaça do cabo depois de andar numa alcatifa ou num campo seco: a caixa continua | -- | Já |
| 3 | 100 ciclos de ligar e desligar durante um jogo: a caixa não reinicia, o barramento não encrava, cada ligação é encontrada em 2 s | Um módulo e o controlador da porta da caixa | **Depois do incremento 8** |
| 6 | Ruído: um módulo de alvo junto a uma sirene e um estroboscópio de 12 V a comutar durante 30 minutos; contar erros de CRC e consultas falhadas | Um módulo | **Depois do incremento 8** |

A linha do registo da caixa para um módulo encontrado na porta, a vista dos
módulos na consola série, e o passo próprio da porta no BRING_UP vêm com o
controlador da porta (**depois do incremento 8**).

## 9. Resolução de problemas

| Sintoma | Causa provável | O que fazer |
| --- | --- | --- |
| O teclado, o leitor NFC ou o medidor deixam de funcionar quando se monta a placa da porta | Um curto do lado «BUS IN», ou pull-ups fortes demais (o lado IN da placa de breakout somado ao da caixa) | Repete a 8.1; mede SDA e SCL ao 3V3 na placa de interligação (1-3,9 kohm) |
| O pino 1 mede 0 V | O díodo ao contrário, o fusível disparado (um curto no cabo ou na tomada), ou uma solda partida | Desliga o cabo, espera um minuto para o fusível arrefecer, mede outra vez; confirma a risca do díodo |
| O pino 1 mede 3,3 V ou mais | O díodo está em ponte ou falta | Corrige o caminho da alimentação: o pino 1 tem de vir através do díodo |
| SDA ou SCL medem 0 V na tomada sem nada ligado | Um curto ao GND na tomada ou no TVS; ou o buffer está a manter a porta desligada porque uma linha está em baixo | Procura uma ponte de solda no adaptador do TVS e nos copos da tomada |
| A caixa reinicia quando se liga um cabo | Um curto entre os pinos 1 e 3 no cabo, capacidade a mais no pino 1, ou falta o fusível | Confirma o cabo pino a pino; não pode haver nenhum condensador maior que 100 nF nos 3,3 V da porta |
| Um módulo não é encontrado | **Esperado até ao incremento 8**: a caixa ainda não procura módulos. Depois disso: o seu endereço (0x58-0x5F), o cabo, a alimentação (cerca de 3,0 V na sua ponta) | -- |

---

Licença: este guia é CC-BY-SA-4.0; o desenho da porta é CERN-OHL-S-2.0, como o
resto do hardware ([LICENSING.md](../../LICENSING.md)).
