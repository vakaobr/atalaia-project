<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Manual de marshal

Para os marshals de um campo: quem faz a cronografagem à entrada e as verificações durante o jogo. Em inglês: [Marshal manual](../en/marshal.md).

> **Ainda não está pronta para o campo.** A Atalaia está em pré-alfa. Nenhum telemóvel a sério foi usado num campo até hoje. Cada passo abaixo corresponde ao que a app mostra hoje. Os passos que dependem de hardware dizem **Ainda não testado num campo**. As palavras em *itálico* estão no [glossário](https://atalaia-project.link/glossario/).

![O ecrã do cronógrafo num telemóvel: os botões do peso da BB, o teclado da velocidade, o botão Registar o disparo e um PASSA verde](../../../site/img/screens/app-chrono-pt.png)

## O que precisas

- Um telemóvel Android (Android 8.0 ou mais recente) com a app Atalaia. Um iPhone serve para o cronógrafo, mas **não tem NFC**: não lê nem grava etiquetas NFC. Para instalar a app, vê o [manual de quem joga](player.md#1-instala-a-app).
- Um cronógrafo, e uma maneira de ver a velocidade da réplica.
- A rede Wi-Fi do campo, pelo menos uma vez, para o controlador te confirmar.
- Para as etiquetas de quem joga: um telemóvel Android com NFC, etiquetas NFC virgens e a **chave de entrada do campo** (vê a [secção 7](#7-grava-as-etiquetas-de-quem-joga)).

## 1. Passa a ser marshal

Só és marshal se a organização te puser na **lista de marshals**. A app não te deixa escolher o teu identificador.

1. Instala a app e escolhe a língua ([manual de quem joga](player.md#2-escolhe-a-língua)).
2. Faz o **Check-in no campo** como participante: **Participante › Check-in no campo**, como no [manual de quem joga](player.md#3-faz-o-check-in-no-campo).
3. Pede à organização que te acrescente. Na consola dela, abre **Check-in › Marshals**, escolhe-te em **Quem fez o check-in** e toca em **Acrescentar marshal**. O controlador dá-te um identificador, por exemplo **M-01**.
4. No teu telemóvel, toca em **Marshal**. A app mostra **A perguntar ao controlador do campo…** e depois **O teu identificador de marshal é M-01 (** *o teu nome* **)**. O identificador e o nome vêm da lista da organização.
5. Se disser **O controlador do campo não te tem na lista de marshals. Pede à organização para te acrescentar como marshal.**, espera pela organização e toca em **Perguntar outra vez**.

A app cria a tua **chave de assinatura** sozinha. Cada disparo que registas é assinado com ela, por isso ninguém pode mudar uma medição depois. Não tens de fazer nada. Em **Quem és** vês **Chave de assinatura**. **Nova chave** cria uma nova. As medições antigas ficam com a chave antiga.

Se a organização te tirar da lista, o teu telemóvel deixa logo de ser de marshal. As medições que ainda não enviaste ficam no telemóvel. Seguem se a organização te voltar a acrescentar.

## 2. O ecrã Marshal

**Marshal** abre uma lista:

| Cartão | Para que serve |
| --- | --- |
| **Réplicas por cronografar** | A lista do campo com as réplicas declaradas que ainda precisam do cronógrafo. |
| **Cronógrafo** | Entrada e verificações: regista disparos e vê PASSA, ATENÇÃO ou CHUMBA. |
| **Registo de réplicas** | As réplicas registadas neste telemóvel. |
| **Etiquetas de quem joga** | Grava etiquetas NFC assinadas para um jogo. |

Mais abaixo, **Quem és** tem **Identificador do cronógrafo** (um nome para o teu aparelho, por exemplo *chrono-1*) e **Chave de assinatura**. **Medições guardadas** diz quantas medições estão neste telemóvel. Guardam-se 365 dias e depois são apagadas. **Apagar as medições de alguém** apaga as medições de uma pessoa: escreve o **Identificador de quem joga** e toca em **Apagar**.

## 3. A lista: réplicas por cronografar

1. Toca em **Réplicas por cronografar**.
2. Em cima vês **Por cronografar: 4 · aprovadas: 2 · recusadas: 0**. Toca no ícone de **atualizar** para pôr a lista em dia.
3. Cada cartão é uma pessoa, com a equipa e as réplicas declaradas. Um símbolo junto de cada réplica diz **por cronografar**, **aprovada** ou **recusada**. Quem ainda não foi confirmado mostra **à espera de confirmação**. Uma réplica sem registo mostra **ainda sem registo**.
4. Para encontrar uma réplica pela etiqueta, toca no ícone de **ler** e aponta a câmara à etiqueta QR dela.
5. Toca numa réplica para a cronografar ([secção 4](#4-cronografa-uma-réplica)).
6. Se cronografares várias réplicas sem ligação, toca em **Enviar** *n* **série(s) por enviar** quando voltares ao Wi-Fi do campo. Uma série que o controlador não aceita fica no teu telemóvel.
7. Alguém sem a app: toca em **Check-in à mão**, escreve o nome e toca em **Fazer o check-in**. O controlador dá-lhe um identificador.

A organização também vê esta lista na consola dela. A lista precisa de a organização confirmar que és marshal.

## 4. Cronografa uma réplica

1. Na lista, toca na réplica. Abre o **Cronógrafo** com a réplica já preenchida.
2. Em **Limites do campo**, escolhe o país que a organização usa: **Portugal**, **United Kingdom**, **Germany** ou **Generic CQB**. O ecrã avisa: **Os limites «…» não estão verificados**. Os valores vêm da pesquisa do projeto. Não são uma fonte oficial nem a lei. Confirma-os com as regras do campo. O controlador também avalia cada série com os limites dele. Se forem diferentes, vale a resposta do controlador.
3. Escolhe **Entrada**. (Usa **Verificação** mais tarde, durante o jogo.)
4. A linha **Limite: 1,14 J (350 fps com 0,20 g)** mostra o limite da classe da réplica. Se disser **Os limites do campo não têm a classe «…».**, escolhe outra lista ou pergunta à organização.
5. Em **Peso da BB**, toca no peso da BB que usas no teste (0,20 g a 0,45 g).
6. Dispara um tiro sobre o cronógrafo. Em **Velocidade**, escolhe **m/s** ou **fps** e escreve o número no teclado. A linha **Energia:** mostra os joules. Fica vermelha acima do limite.
7. Toca em **Registar o disparo**. Repete para cada disparo da série.
8. Depois de cada disparo vês o resultado:
   - **PASSA** (verde): a energia mais alta da série está no limite ou abaixo dele.
   - **ATENÇÃO** (âmbar): só numa verificação. Abaixo do limite, mas acima da energia da réplica na entrada mais 5%.
   - **CHUMBA** (vermelho): acima do limite.
   O símbolo diz **Mais alta: 0,925 J · limite 1,14 J**. A lista por baixo mostra cada disparo com m/s, fps, peso da BB e energia.
9. Toca em **Enviar ao controlador**. Vês **Enviado: aprovada.**, **Enviado: recusada.** ou **Enviado: aviso.** O símbolo da réplica na lista muda.
10. Toca em **Nova série** para a réplica seguinte.

Qualquer penalização é sempre decidida por uma pessoa. A app mostra os números. Não te fies só numa cor.

Se a réplica não estiver na lista, a app regista-a por ti quando lhe tocas na lista. Vê a [secção 6](#6-o-registo-de-réplicas).

Uma aprovação vale para o resto do dia ou só para este jogo, conforme as regras do campo.

## 5. Verificações durante o jogo

1. Abre **Marshal › Cronógrafo**.
2. Escolhe **Verificação**.
3. Escolhe a réplica em **Réplica**, ou encosta a etiqueta NFC da réplica às costas do telemóvel (só Android). Se a etiqueta não estiver no registo, diz **Esta etiqueta não está no registo de réplicas.**
4. Regista os disparos, como numa entrada.
5. O símbolo mostra o resultado e **Na entrada: 0,88 J (+5% de tolerância)** quando o teu telemóvel tem a entrada da réplica.
6. Abre a lista para enviar a série.

Um ATENÇÃO ou um CHUMBA aparece à organização no registo dela como um acontecimento `chrono.violation`.

## 6. O registo de réplicas

O registo do teu telemóvel lista as réplicas que conheces.

1. Toca em **Registo de réplicas**. Diz **n réplicas registadas**.
2. Para juntar uma, toca em **Registar réplica** e preenche **Identificador de quem joga**, **Tipo**, **Classe** e **Marca e modelo**.
3. Em **Etiqueta da réplica**, encosta a etiqueta NFC da réplica ao telemóvel, ou toca em **Ler etiqueta QR**. Depois toca em **Guardar**.

Uma réplica que cronografas a partir da lista fica registada automaticamente. O registo mostra o código da etiqueta dela (**ATL-** e oito caracteres). Podes escrever esse código num autocolante. A app ainda não imprime etiquetas. Qualquer código QR que tenha esse texto pode ser lido.

## 7. Grava as etiquetas de quem joga

Alguns modos (Baixa Confirmada, Reentradas e Vidas, Registo de Presença, Ligaduras, Fábrica de Dinheiro) precisam de que cada pessoa leve uma etiqueta NFC. Gravas as etiquetas no teu telemóvel. Isto precisa de um telemóvel Android com NFC. Ainda não testado num campo.

1. Pede à organização a **chave de entrada do campo** (64 algarismos e letras). Na app, abre a roda dentada (**Definições**) e em **Campo** toca em **Chave de entrada do campo**. Escreve-a e toca em **Guardar**. Mantém-na privada: é o segredo-mestre do campo.
2. Pede à organização que abra o separador **Juntar** da consola para o jogo e mostre um **código QR** ou um **Texto de entrada**.
3. Toca em **Etiquetas de quem joga** e depois em **Escolher o jogo**. Lê o código QR, encosta um cartão de entrada ao telemóvel, ou cola o texto e toca em **Usar este texto**. O ecrã mostra **Jogo 17 (org.atalaia.domination)**.
4. Escreve o **Identificador de quem joga** (aparece na página **O meu check-in** da pessoa, por exemplo *p-17*). Escolhe a equipa, ou **Sem equipa**.
5. Toca em **Escrever a etiqueta**. Quando disser **Encosta a etiqueta às costas do telemóvel…**, mantém-na quieta até ficar escrita. Aparece depois em **Escritas agora**.
6. Repete para cada pessoa.

Uma etiqueta só funciona no jogo para que foi gravada. Cada jogo novo precisa de etiquetas novas.

## 8. Limites sem ligação

O «sim» do controlador é o que faz do teu telemóvel um marshal. Funciona assim:

- A app pergunta ao controlador de cada vez que abres **Marshal** e outra vez de 10 em 10 minutos, mais ou menos, enquanto puder.
- Se o controlador não for alcançável, o teu telemóvel continua a ser de marshal durante **cerca de 2 horas** depois do último «sim». Vês **Sem ligação: o controlador do campo confirmou-te como marshal M-01 em** *data* **. Vale até** *data*.
- Depois disso, vês **Sem ligação ao controlador do campo, e a confirmação de … caducou. Liga-te à rede do campo e pergunta outra vez.** Não podes registar medições até o fazeres.
- Um telemóvel que **nunca** foi confirmado não pode trabalhar sem ligação: **Sem ligação ao controlador do campo, e este telemóvel ainda não foi confirmado como marshal aqui.** Liga-te ao Wi-Fi uma vez.
- As medições que fizeste ficam no telemóvel e são enviadas mais tarde.

Conta voltar ao Wi-Fi do campo de duas em duas horas.

## Resolução de problemas

| Problema | O que fazer |
| --- | --- |
| **Primeiro faz o check-in no campo com o cartaz** | Ainda não fizeste o check-in. Toca em **Check-in no campo** na mensagem, ou vai a **Participante › Check-in no campo**. |
| **Este check-in já não é válido: faz o check-in outra vez.** | Faz o check-in outra vez no campo. |
| **Pede à organização para te acrescentar como marshal** | A organização tem de te acrescentar em **Check-in › Marshals**. Depois toca em **Perguntar outra vez**. |
| **A organização retirou-te da lista de marshals** | A organização retirou-te. As séries por enviar ficam no telemóvel. Pede-lhe que te volte a acrescentar. |
| **Registar o disparo** está cinzento | Precisas de uma réplica, de um limite para a classe dela e de uma velocidade. Escolhe primeiro uma réplica. |
| **Não foi enviado … Fica neste telemóvel para enviar depois.** | Não foi possível chegar ao controlador. Liga-te ao Wi-Fi do campo e toca em **Enviar** *n* **série(s) por enviar** na lista. |
| **n série(s) não foram aceites porque o controlador não te tem na lista de marshals** | Pede à organização que te volte a acrescentar. As séries esperam no teu telemóvel. |
| **Esta réplica não está declarada neste jogo** | Escolhe a declaração da pessoa na lista. Ela tem de declarar primeiro a réplica. |
| A etiqueta NFC não grava | **Esta etiqueta está bloqueada**, **é pequena demais** ou **não aceita dados NDEF**: usa uma etiqueta NTAG nova. Mantém a etiqueta quieta. Num iPhone não podes gravar etiquetas. |
| **Primeiro define a chave de entrada do campo nas definições.** | Escreve a chave de entrada do campo em **Definições › Chave de entrada do campo**. |

Mais ajuda: pergunta à organização, ou nas [Discussões](https://github.com/vakaobr/atalaia-project/discussions) do projeto.
