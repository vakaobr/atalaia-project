<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Guia de montagem do módulo de alvo

Em inglês: [Target addon build guide](BUILD.md).

O módulo de alvo é uma placa a que se dispara, com um sensor piezo que sente
cada impacto e uma pequena placa RP2040 própria, que se liga à
[porta de expansão](../expansion-port/BUILD.pt.md) de uma caixa e a transforma
num alvo com pontuação: o hardware do modo *Janelas de Alvo*, em que um
impacto enquanto o alvo mostra a cor de uma equipa pontua para essa equipa.
Escrito para alguém do clube que saiba soldar pinos e fios e usar um
multímetro.

> **Estado: o hardware e o firmware estão decididos e podem ser montados;
> ainda não testados numa placa de alvo real nem numa caixa real.** O rascunho do RFC «The expansion port»
> ([`docs/rfcs/0000-expansion-port.md`](../../docs/rfcs/0000-expansion-port.md),
> aprovado por quem mantém o projeto em 2026-11-03) decidiu o que este guia
> listava como em aberto: o processador (uma placa RP2040, EXP-15), o
> endereço (0x58, EXP-7), a resposta «identify» e o relatório de impactos (o
> protocolo de expansão v1,
> [`protocol/expansion-port.md`](../../protocol/expansion-port.md), EXP-9), o
> circuito do sensor em linhas gerais e a proteção da porta (EXP-4). O
> **incremento 8** do plano do RFC juntou o firmware: o firmware do próprio
> módulo em pico-sdk
> ([`firmware/target-module/`](../../firmware/target-module/README.md), com o
> seu ficheiro UF2 vindo da CI e das versões publicadas), a sua tabela de
> pinos ([secção 6](#6-o-módulo-passo-a-passo)), e o controlador da porta da
> caixa chamado pela sua tarefa de jogo, por isso uma caixa encontra o módulo,
> lista `hit` e passa cada impacto ao script do modo. Tudo isto está testado
> só num computador (as partes portáteis do módulo, e uma caixa contra um
> módulo simulado com o mesmo código de protocolo); a
> [secção 10](#10-o-que-ainda-espera) lista o que espera pela bancada, e
> *Janelas de Alvo* ainda não é uma predefinição da Field Box (passa a ser
> depois de testado em bancada). **Ainda não se montou nenhum alvo a partir
> deste guia.** Os passos marcados **Verifica na
> primeira montagem** são questões em aberto; conta o que encontrares numa
> issue. As fotografias serão juntadas depois da primeira montagem (fase HW2
> do plano); este guia nunca usa fotografias de maquetas nem geradas.

## Índice

1. [O que estás a montar](#1-o-que-estás-a-montar)
2. [O que está decidido e o que não está](#2-o-que-está-decidido-e-o-que-não-está)
3. [Peças](#3-peças)
4. [Ferramentas e segurança](#4-ferramentas-e-segurança)
5. [O lado da caixa: a porta de expansão](#5-o-lado-da-caixa-a-porta-de-expansão)
6. [O módulo, passo a passo](#6-o-módulo-passo-a-passo)
7. [Verificações na montagem](#7-verificações-na-montagem)
8. [Placa de alvo, suporte e invólucro](#8-placa-de-alvo-suporte-e-invólucro)
9. [Como a caixa lê os impactos](#9-como-a-caixa-lê-os-impactos)
10. [O que ainda espera](#10-o-que-ainda-espera)
11. [Fotografias](#11-fotografias)
12. [Ajudar](#12-ajudar)

## 1. O que estás a montar

```
placa ── almofada de borracha ── disco piezo ── entrada ── placa RP2040 ── M12 (macho) ═══ cabo de 2 m ═══ M12 (fêmea) ── placa da porta ── caixa
         (aço ou policarbonato)                 (divisor,    (ADC, alvo I2C   pino 1 3,3 V, 2 SDA,                    (buffer, TVS,
                                                 dreno,       em 0x58)        3 GND, 4 SCL, 5 n.l.                     fusível, díodo)
                                                 limitadores)
```

- O **disco piezo**, colado através de uma almofada de borracha às costas da
  placa de alvo, transforma cada impacto num pico de tensão curto.
- O **circuito de entrada** (um divisor de resistências, um dreno de 1 Mohm,
  dois díodos Schottky limitadores) ajusta o pico à gama do ADC do RP2040 e
  mantém-no entre o GND e os 3,3 V.
- A **placa RP2040** amostra o piezo continuamente, encontra o pico de cada
  impacto (a sua força, 0-255) com um tempo de espera contra a vibração da
  placa, guarda-o com a sua idade até a caixa o recolher, e responde às
  leituras I2C da caixa no endereço **0x58** (EXP-10, EXP-15).
- A **caixa** lê o `STATUS` do módulo a cada 20 ms pela sua porta de
  expansão, e passa cada impacto ao script do modo como `hit.hit` com a sua
  `strength`.

*Janelas de Alvo* acende o **anel de luzes da própria caixa**, por isso o
módulo não precisa de luzes (P5J-16). Custo aproximado: 10-15 € para o módulo
sem a placa de alvo nem o cabo (RFC, secção 3), mais a placa de alvo, o cabo e
a porta da caixa ([guia da porta](../expansion-port/BUILD.pt.md), 6-14 €);
preços do mercado de amadores, não é um orçamento.

## 2. O que está decidido e o que não está

| O quê | Decidido | Onde |
| --- | --- | --- |
| Finalidade | Um alvo com pontuação de impactos para qualquer caixa (Field Box, Satélite, módulo de E/S) | [Especificação de conceção](../../docs/design-spec.md), secção 6; EXP-2 |
| Como se liga | A **porta de expansão** da caixa: uma tomada M12 de codificação A, 5 pinos, só 3,3 V (1 castanho 3,3 V, 2 branco SDA, 3 azul GND, 4 preto SCL, 5 cinzento não ligado), atrás da placa da porta da caixa | EXP-1, EXP-4; [guia da porta](../expansion-port/BUILD.pt.md) |
| Processador | Uma **placa RP2040** (da classe RP2040-Zero, ou um Pico), a um relógio reduzido (48 MHz) para ficar dentro da corrente da porta | EXP-15; RFC, secção 3 (a) |
| Energia vinda da caixa | No máximo **25 mA** dos 3,3 V da porta (cerca de 3,0 V no módulo), para o processador e o circuito de entrada do sensor; **medidos** na primeira montagem | EXP-3; P5J-16 |
| Pull-ups | **Nenhum** no módulo: a placa da porta da caixa tem-nos | EXP-4; P5J-17 |
| Polaridade invertida | O módulo protege-se de um cabo feito à mão e mal ligado: um MOSFET de canal P na sua alimentação ([secção 6.1](#61-entrada-da-alimentação)) | RFC, secção 1 («Plugging in reversed»); este guia (EXPI10-8) |
| Endereço | **0x58**; dois jumpers de solda somam 1-3 (0x59-0x5B) para um segundo alvo na mesma caixa | EXP-7 |
| «Identify» e o relatório de impactos | O protocolo de expansão v1: `IDENT` (modelo 0x0001 `target`, um canal), `CHANNEL` (tipo hit), `STATUS` (o impacto mais antigo com a sua sequência, força e idade), `COMMAND` (`ACK`, `ARM`, `CONFIG` para o limiar, o tempo de espera e o debounce, `LOCATE`). Substitui o rascunho de 5 bytes da P5J-19, para o qual nada foi montado | EXP-9, EXP-10; [protocol/expansion-port.md](../../protocol/expansion-port.md) |
| Sensor | Um disco piezo de 27-35 mm, colado às costas da placa de alvo através de uma almofada de borracha; um divisor de resistências e um dreno de 1 Mohm para acertar o nível, díodos Schottky limitadores para os 3,3 V e o GND, para um pino do ADC | RFC, secção 3 (a) |
| Deteção de impactos | No módulo: um pico acima do limiar, escalado para 0-255, um tempo de espera (50 ms por omissão) contra a vibração; pelo menos 16 impactos em fila, cada um com a sua idade | EXP-10 |
| Placa de alvo | Aço ou policarbonato, inclinada para baixo, com a eletrónica atrás | RFC, secção 3 (a); [secção 8](#8-placa-de-alvo-suporte-e-invólucro) |
| O que os scripts de jogo da caixa veem | A capacidade `hit`: um evento `hit` com uma `strength` de 0 a 255 (os scripts recebem `hit.hit`), e os comandos `arm` e `disarm` | Especificação de conceção, secção 7; rascunho do RFC 0000, Aditamento 1; EXP-18 |
| O firmware | O firmware do módulo em pico-sdk, sobre o núcleo de módulo do incremento 7 ([`firmware/target-module/`](../../firmware/target-module/README.md)): o ADC amostrado a 20 kamostras/s por DMA, o detetor de picos, o alvo I2C, o `LOCATE` num LED; ficheiros UF2 vindos da CI e das versões publicadas (`atalaia-target-module-<versão>.uf2`, e `-2-` para um módulo de duas placas) | Incremento 8 do RFC; EXPI8-8 a EXPI8-13 |
| Os pinos do módulo | Alvo I2C em **GP4** (SDA) e **GP5** (SCL), o piezo em **GP26** (ADC0; uma segunda placa em GP27), os jumpers de endereço em **GP2** e **GP3**, o LED do `LOCATE` em **GP14** ([secção 6](#6-o-módulo-passo-a-passo)) | EXPI8-9 |
| O modo de jogo | *Janelas de Alvo* (`modes/target_windows/`): o papel `target` precisa de `hit` e `led`. O alvo fica escuro durante `interval_s`, depois acende a cor de uma equipa ao acaso durante `window_s`; um impacto de pelo menos `min_strength` na janela dá `hit_points` a essa equipa. Construído e testado no simulador, e de ponta a ponta com a caixa no anfitrião e um módulo simulado; predefinição da Field Box quando o alvo estiver testado em bancada | [Plano da fase 4](../../docs/phase-4-site-server/PLAN.md), fase 2 do plano; M2-1 a M2-5; incremento 8 do RFC; EXPI8-14 |

Não decidido, ou ainda não feito:

1. **O módulo em hardware real**: a sua corrente a 48 MHz (abaixo de 25 mA,
   teste de bancada 4) e a tensão no seu pino 3V3
   ([secção 6.1](#61-entrada-da-alimentação)); o firmware só correu num
   computador.
2. **A escala de força, o limiar e o tempo de espera** em placas reais de aço
   e de policarbonato (teste de bancada 8, HW2), e com eles as duas
   resistências do divisor do circuito de entrada.
3. **O tamanho e a espessura da placa de alvo, o seu suporte e a sua
   inclinação** (HW2).
4. **Uma placa de circuito impresso** para o módulo: mais tarde; placa
   perfurada até lá.

## 3. Peças

Um alvo. A porta da caixa é um conjunto de peças à parte
([guia da porta, secção 3](../expansion-port/BUILD.pt.md#3-peças-e-contra-o-que-protege-cada-uma)).

| # | Peça | Qtd | Para que serve | O que verificar |
| --- | --- | --- | --- | --- |
| 1 | Placa RP2040: da classe **RP2040-Zero** (ou um Raspberry Pi Pico) | 1 | Amostra o piezo, encontra os impactos, responde à caixa em 0x58 | Um RP2040 genuíno com a sua USB-C (ou micro-USB) para gravar por UF2 |
| 2 | Disco piezo, **27-35 mm**, com fios | 1 (2 de reserva) | Sente cada impacto através da placa de alvo | Disco de latão com o centro cerâmico; compra de reserva, partem |
| 3 | Almofada de borracha (2-3 mm, neopreno ou EPDM) e cola de contacto | 1 | Cola o piezo à placa de alvo e espalha o choque, para um impacto direto não o partir | Cobre o disco todo |
| 4 | Resistência de 1 Mohm, 1/4 W | 1 | O **dreno** aos terminais do piezo: escoa a sua carga, para o ADC ver um pico e não um nível a derivar devagar | |
| 5 | Duas resistências para o divisor (valores escolhidos em placas reais) e uma barra de 2 contactos para cada uma | 2 | Ajustam o pico à gama do ADC | Monta-as em suportes, para se poderem trocar no teste de bancada 8 |
| 6 | Díodos Schottky pequenos, da classe **BAT85** | 2 | **Limitadores**: mantêm o pino do ADC entre o GND e os 3,3 V, faça a placa de alvo o que fizer | Tensão direta baixa |
| 7 | MOSFET de canal P para uma tensão de porta baixa, da classe **AO3401** ou SI2301 (SOT-23), num adaptador SOT-23; uma resistência de 10 kohm | 1 de cada | **Proteção contra polaridade invertida** da alimentação do módulo, quase sem queda de tensão (um díodo tiraria mais 0,3 V, e o nível alto do barramento ficaria acima da alimentação do módulo) | Para uma tensão de porta de -2,5 V ou menos |
| 8 | Jumpers de solda ou um interruptor DIP de 2 posições | 1 | O endereço: aberto-aberto é 0x58; os outros 0x59-0x5B | Entre GP2 e GND (+1) e entre GP3 e GND (+2) |
| 8a | LED de 3 mm (qualquer cor) e uma resistência de 1 kohm | 1 de cada | Pisca enquanto a caixa pede ao módulo que se mostre (`LOCATE`), para o encontrar no campo | Em GP14; cerca de 1 mA, só enquanto pisca |
| 9 | Conector de painel M12 de codificação A, 5 pinos, **macho**, IP67 | 1 | A ponta do cabo do lado do módulo | Codificação A, 5 pinos |
| 10 | Cabo de extensão de sensor M12 de codificação A, 5 polos, macho-fêmea, 1-2 m | 1 | Da caixa ao módulo, no máximo 2 m | Confirma as cores com um multímetro |
| 11 | Invólucro IP65 pequeno, bucim ou o conector M12 na parede, placa perfurada, fio de 0,25 mm², manga termorretrátil | 1 conjunto | Guarda a placa RP2040 e o circuito de entrada atrás da placa de alvo | De preferência não metálico; fora da linha de fogo |
| 12 | Placa de aço ou folha de policarbonato, e um suporte | 1 | Aquilo para onde os jogadores disparam | Tamanho, espessura e suporte: HW2 ([secção 8](#8-placa-de-alvo-suporte-e-invólucro)) |

## 4. Ferramentas e segurança

As ferramentas são as da Field Box ([manual, secção 3](../field-box/BUILD.pt.md#3-ferramentas-e-consumíveis)).
Na bancada:

1. **Nunca ligues ao mesmo tempo o cabo USB do módulo e o cabo da porta.**
   Grava o módulo com a porta desligada.
2. **Só 3,3 V** em todos os pinos do conector do módulo; **o pino 5 sem
   ligação**; **sem pull-ups** no módulo; **no máximo 25 mA** (P5J-16,
   P5J-17).
3. **Nada de luzes na alimentação da porta.** Um módulo com luzes próprias
   precisa de uma célula própria, com o seu fusível e a sua carga, o seu GND
   unido ao da porta, e a sua alimentação nunca chega à porta.
4. **Estática**: toca no GND da caixa antes de ligares um módulo.

Sempre que alguém dispara para o alvo, também na bancada:

- **Proteção dos olhos e da cara** para todas as pessoas ao alcance do alvo,
  incluindo enquanto o sensor é afinado.
- **Ricochetes.** As BB ressaltam numa placa dura, e algumas voltam para
  trás. Inclina uma placa de aço de modo a mandá-las para o chão, nunca de
  frente para quem dispara. Nunca dispares para a caixa, o cabo, o conector
  ou o invólucro do módulo, só para a placa de alvo.
- **Protege a eletrónica.** O módulo, as suas ligações e o cabo ficam atrás
  da placa de alvo ou no seu próprio invólucro, fora da linha de fogo.
- **Os limites de potência do campo** (o cronógrafo, o limite em joules)
  aplicam-se a disparar para alvos como a disparar para jogadores; o alvo não
  é razão para os subir.
- **Um adereço de jogo**: cores vivas e uma etiqueta «GAME PROP», como todos
  os dispositivos Atalaia; a caixa onde se liga segue as regras de bateria do
  seu próprio guia de montagem
  ([Field Box](../field-box/BUILD.pt.md#4-regras-de-segurança),
  [Satélite](../satellite/BUILD.pt.md#4-ferramentas-e-segurança)).

## 5. O lado da caixa: a porta de expansão

A caixa precisa de uma porta de expansão: a tomada M12 e a sua placa da porta
(o buffer de ligação a quente, a matriz TVS, as resistências de 100 ohm, o
fusível de 50 mA e o díodo contra a alimentação inversa). Monta-a e verifica-a
pelo [guia de montagem da porta de expansão](../expansion-port/BUILD.pt.md); é
a mesma na Field Box, no Satélite e no módulo de E/S, e não usa nenhum GPIO. A
sua tabela de pinos é verificada contra o firmware pelo
`tools/check_wiring.py`
([guia da porta, secção 5](../expansion-port/BUILD.pt.md#5-os-pinos-da-porta)).

As regras que o módulo segue, das mesmas decisões:

- **Nada acima de 3,3 V em nenhum pino.** O módulo funciona com os 3,3 V da
  porta (cerca de 3,0 V depois do díodo da caixa); uma peça que precise de
  mais tira-a de uma alimentação própria, que nunca se liga à porta.
- **Nenhuma resistência de pull-up em SDA ou SCL** no módulo (P5J-17). Se a
  placa RP2040 que usas tiver alguma nos pinos que escolheres, tira-a.
- **No máximo 25 mA** do pino 1 (P5J-16). Espera-se que um RP2040 a 48 MHz e
  o circuito de entrada fiquem abaixo disso; **a medir** (teste de bancada 4).

### Porquê 25 mA

O regulador de 3,3 V da placa já alimenta a placa (o ESP32-S3 e o rádio: cerca
de 80-150 mA, com picos de 400-500 mA enquanto o Wi-Fi ou o rádio transmitem), o
TFT com a sua retroiluminação (40-100 mA), o PN532 (50-150 mA com o campo
ligado), e o expansor do teclado e o medidor (menos de 1 mA): cerca de 170-400
mA num jogo, com picos perto de 750 mA
([orçamento de energia da Field Box](../field-box/BUILD.pt.md#orçamento-de-energia-estimativas-não-medições),
estimativas, não medições). A porta promete só uma parte pequena e fixa: 25 mA
são cerca de 3 % desses picos, e o fusível impede que um curto-circuito no cabo
ou no conector deixe a caixa sem energia. Um só LED WS2812 consome até 60 mA,
por isso luzes na porta estão fora de questão.

## 6. O módulo, passo a passo

Dispõe o módulo numa pequena placa perfurada: a placa RP2040 em pinos, o
circuito de entrada junto ao seu pino do ADC, o MOSFET junto ao seu pino 3V3,
e os fios do conector M12 num bordo.

Os pinos do módulo, como o seu firmware os usa (`firmware/target-module/src/main.c`;
os mesmos números de GPIO numa RP2040-Zero e num Pico; decisão EXPI8-9):

| Pino do RP2040 | O quê | Liga a |
| --- | --- | --- |
| 3V3 | A alimentação do módulo, cerca de 3,0 V | Pino 1 do M12 (castanho), através do MOSFET ([6.1](#61-entrada-da-alimentação)) |
| GND | Massa | Pino 3 do M12 (azul) |
| GP4 | SDA do I2C0, o alvo I2C (sem pull-up) | Pino 2 do M12 (branco) |
| GP5 | SCL do I2C0, o alvo I2C (sem pull-up) | Pino 4 do M12 (preto) |
| GP26 | ADC0: o piezo | O nó do ADC do circuito de entrada ([6.2](#62-o-piezo-e-o-seu-circuito-de-entrada)) |
| GP27 | ADC1: a segunda placa (só no firmware de duas placas) | Um segundo circuito de entrada |
| GP2 | Jumper de endereço A0: fechado ao GND soma 1 | Jumper ao GND |
| GP3 | Jumper de endereço A1: fechado ao GND soma 2 | Jumper ao GND |
| GP14 | O LED do `LOCATE` | Ânodo do LED; o cátodo ao GND através de 1 kohm |

O LED do próprio Pico (GP25) pisca com o GP14; o LED RGB de uma RP2040-Zero
fica apagado.

### 6.1 Entrada da alimentação

1. **Pino 1** do M12 (castanho) ao **dreno** do MOSFET; a sua **fonte** ao
   pino **3V3** da placa RP2040; a sua **porta** ao GND através de 10 kohm.
   Com a polaridade certa o MOSFET liga-se por completo; com os pinos 1 e 3
   trocados num cabo feito à mão fica desligado.
2. **Pino 3** do M12 (azul) ao **GND** da placa.
3. **Nunca** ao pino 5V / VBUS / VSYS da placa: esse é o lado da USB.
4. **Pino 5** do M12 (cinzento): cortado curto e isolado, sem ligação.
5. **Numa RP2040-Zero** os 3,3 V da porta vão ao pino **3V3**, a saída do seu
   próprio regulador, que fica sem alimentação (a sua entrada são os 5 V da
   USB). **Num Pico** o mesmo pino, com o **3V3_EN ligado ao GND**, para o
   regulador comutado do próprio Pico ficar desligado e não lutar com a porta
   (EXPI8-10).
6. **Verifica na primeira montagem:** a tensão no pino 3V3 com o módulo a
   funcionar (espera-se cerca de 3,0 V) e a corrente (teste de bancada 4).

### 6.2 O piezo e o seu circuito de entrada

```
piezo + ──┬── R1 ──┬──────────────── pino do ADC
          │        ├── R2 ── GND
        1 Mohm     ├── BAT85 (cátodo ao 3V3)
          │        └── BAT85 (ânodo ao GND, cátodo ao nó do ADC)
piezo − ──┴── GND
```

1. Cola o disco piezo à almofada de borracha e a almofada às costas da placa
   de alvo, ao centro, com o lado de latão virado para a almofada. Deixa a
   cola curar como o fabricante diz.
2. O dreno de **1 Mohm** aos terminais do piezo, no módulo.
3. **R1** do terminal + do piezo ao nó do ADC; **R2** do nó do ADC ao GND
   (as duas em suportes: os valores vêm do teste de bancada 8).
4. Os dois limitadores **BAT85** no nó do ADC: um com o cátodo (a risca) ao
   3V3 e o ânodo ao nó; o outro com o cátodo ao nó e o ânodo ao GND.
5. O nó do ADC ao **GP26** (ADC0). O segundo circuito de entrada de um módulo
   de duas placas vai ao GP27 (ADC1), com o ficheiro UF2 de duas placas.
6. Passa os fios do piezo entrançados, presos, atrás da placa de alvo.

### 6.3 Barramento e endereço

1. **Pino 2** do M12 (branco, SDA) ao **GP4** e **pino 4** (preto, SCL) ao
   **GP5**: o I2C0 do RP2040, que o firmware usa como alvo I2C. Fios curtos;
   sem pull-ups (o firmware desliga os do próprio RP2040).
2. Os dois jumpers de endereço: **GP2** ao GND soma 1, **GP3** ao GND soma 2.
   Os dois abertos é **0x58**, o endereço que todas as caixas procuram
   primeiro. Deixa-os abertos, a não ser que a caixa leve um segundo alvo. O
   módulo lê-os uma vez, ao ligar: muda-os com o cabo desligado.
3. O **LED** do `LOCATE`: GP14 ao ânodo do LED, o cátodo ao GND através de
   1 kohm, atrás de um pequeno furo no invólucro.

### 6.4 O conector e o invólucro

O conector M12 macho na parede do invólucro, com o O-ring do lado de fora, e
o invólucro atrás da placa de alvo com o conector virado para longe de quem
dispara ([secção 8](#8-placa-de-alvo-suporte-e-invólucro)). Manga
termorretrátil em todos os copos de solda.

## 7. Verificações na montagem

Com um multímetro, o módulo sem alimentação:

- [ ] Pino 1 ao pino 3 do M12: sem curto-circuito.
- [ ] Pino 5 do M12: aberto a todos os outros pinos.
- [ ] Pinos 2 e 4 do M12 ao pino 1: **sem pull-up** (aberto, ou acima de
      100 kohm).
- [ ] O nó do ADC ao GND: R2 em paralelo com o resto; ao 3V3 e ao GND, os
      limitadores medem como díodos (cerca de 0,2-0,4 V num sentido, aberto no
      outro).
- [ ] Os terminais do piezo: cerca de 1 Mohm (o dreno).

Com o firmware:

1. **Gravar o módulo**: carrega no botão BOOT da placa enquanto ligas o cabo
   USB a um computador, e arrasta o ficheiro UF2 do módulo de alvo para a
   unidade que aparece (com a porta desligada):
   `atalaia-target-module-<versão>.uf2` de uma versão publicada (confirma-o
   com o `SHA256SUMS`), ou `firmware/target-module/build/atalaia_target_module.uf2`
   de `python3 tools/docker_module.py build`. O módulo de duas placas leva o
   `atalaia-target-module-2-<versão>.uf2`. Desliga o cabo USB.
2. **Corrente** (teste de bancada 4): um multímetro em série com o pino 1, o
   módulo a amostrar: **abaixo de 25 mA**.
3. **Encontrado pela caixa**: liga o módulo à porta de uma caixa; em 2 s o
   registo série da caixa diz `expansion: 0x58 added: 58:target/1.0.0:hit`, e
   `@modules` na sua consola série lista-o
   (`[{"address":"58","model":"target","fw":"1.0.0","caps":["hit"],"armed":0,...}]`).
   Num jogo, a consola de GM mostra o alvo como uma etiqueta debaixo da caixa.
4. **Armado num jogo**: começa *Janelas de Alvo* na caixa; `@modules` mostra
   `"armed":1`, e uma pancada na placa de alvo regista
   `expansion: hit hit, strength <n>`.
5. **Afinação** (teste de bancada 8): limiar, tempo de espera e escala de
   força em placas de aço e de policarbonato, ao limite em joules do campo,
   com proteção dos olhos; troca R1 e R2 até um impacto à distância ficar bem
   acima do limiar e um impacto mesmo por cima do piezo não chegar aos
   limitadores (saturaria).

## 8. Placa de alvo, suporte e invólucro

Decidido: uma placa de **aço ou policarbonato**, **inclinada para baixo** para
as BB irem para o chão, com a **eletrónica atrás da placa** ou no seu próprio
invólucro, fora da linha de fogo (RFC, secção 3 (a)). Ainda não decidido
(HW2): o tipo de material, a espessura e o tamanho da placa, o suporte e a
inclinação exata; as primeiras montagens decidem-nos e esta secção ganha-os,
com fotografias. Até lá:

- o piezo colado através da almofada às costas da placa de alvo, e o
  invólucro do módulo preso ao suporte, não à placa (para o choque da placa
  não abanar a eletrónica);
- o cabo sai do invólucro para baixo e passa pelo chão, atrás da placa de
  alvo, até à caixa, que fica fora da linha de fogo.

## 9. Como a caixa lê os impactos

A Field Box usa os oito GPIO da placa que não têm nenhuma peça da placa, e o
conector GNSS fica com os 34 e 38-42, por isso não há pino para uma linha de
interrupção. Não precisa de uma (P5J-18, EXP-8):

- Todo o tráfego I2C da caixa, incluindo o do teclado, corre no seu ciclo de
  jogo a cada 10 ms; uma interrupção só seria vista no tique seguinte. A
  caixa lê o `STATUS` de 9 bytes do módulo a cada **20 ms**: uma escrita do
  ponteiro, um novo início e 9 bytes, cerca de 12 bytes no fio (1,1 ms), cerca
  de **5 %** do barramento. A leitura do teclado já usa cerca de 18 %.
- **Latência.** Um impacto chega ao script em cerca de 21 ms depois de o
  módulo o sentir, contra um objetivo de 50 ms: uma janela fica aberta pelo
  menos 1 s (5 s por omissão), e uma BB leva 0,2-0,3 s a atravessar 20-30 m de
  qualquer forma. Quando o ciclo de jogo está lento (uma leitura NFC pode
  segurá-lo 200 ms), os impactos não se perdem: o módulo guarda pelo menos 16,
  com a sua idade, e a caixa data cada um no seu próprio relógio
  (`t_event = t_read - age`).
- A caixa confirma cada impacto pelo seu número de sequência, por isso uma
  confirmação perdida nunca conta um impacto duas vezes; arma e desarma o
  módulo como o modo pede; um módulo que falhe 25 leituras seguidas (0,5 s)
  desaparece, e o controlador é avisado (`node.module_lost` durante um jogo).

O controlador da porta da caixa (`firmware/esp32/main/expansion.c`, chamado
pela tarefa de jogo através do `expansion_box.c` desde o incremento 8) faz
tudo isto: lista `hit` no HELLO da caixa e o módulo no `node.modules`
(`58:target/1.0.0:hit`), arma a placa de alvo só enquanto decorre um jogo e o
modo a armou (`cap("hit"):arm()`), e passa cada impacto ao script como
`hit.hit` com a sua `strength` (e `channel` numa caixa com duas placas). Está
testado num computador contra os vetores partilhados do protocolo e contra um
módulo de alvo simulado sobre o mesmo núcleo de módulo que o real usa.

## 10. O que ainda espera

- A bancada (HW2): a corrente do módulo e a tensão no seu 3V3, a escala de
  força, o limiar e o tempo de espera em placas reais (teste de bancada 8), as
  duas resistências do circuito de entrada, os testes 3 e 6 da porta com um
  módulo ([guia da porta, secção 8.3](../expansion-port/BUILD.pt.md#83-testes-de-bancada)).
- *Janelas de Alvo* como predefinição da Field Box: depois de testado em
  bancada (a linha 8 do RFC, P4R23). Até lá, um campo põe-no numa caixa como
  qualquer outro modo.
- O módulo de E/S a emprestar `hit` a um telemóvel (incremento 9, sobre o
  controlador da porta do 8).

## 11. Fotografias

<!-- PHOTO: target-addon-plate.jpg | the finished target: plate and sensor mounting, front and back -->
> **Fotografia a juntar depois da primeira montagem:** o alvo acabado, a placa
> e a montagem do sensor, de frente e de trás.

<!-- PHOTO: target-addon-port.jpg | the M12 expansion port on a box, and the module's cable plugged in -->
> **Fotografia a juntar depois da primeira montagem:** a porta de expansão M12
> numa caixa, com o cabo do módulo ligado.

## 12. Ajudar

Monta um e conta numa issue o que mediste (a corrente, a tensão no módulo, o
tempo de subida, a afinação nas tuas placas); os itens **Verifica na primeira
montagem** e as dimensões da placa de alvo vêm desses relatos. Os desenhos são
CERN-OHL-S-2.0, como o resto do hardware ([LICENSING.md](../../LICENSING.md)).

---

Licença: este guia é CC-BY-SA-4.0.
