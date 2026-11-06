<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Guia de montagem do controlador (Raspberry Pi)

Para quem na organização monta o **controlador de campo** num Raspberry Pi. Precisas de saber escrever comandos num terminal. Não precisas de escrever código. Os pormenores para quem desenvolve estão no [guia do controlador](../../../controller/README.md) (em inglês). Dirigir o jogo está no [Manual da organização](game-master.md). Para usar um telemóvel Android como controlador, vê o [Guia do telemóvel controlador](phone-controller.md). Em inglês: [Controller setup guide](../en/controller-setup.md).

> **Ainda não está pronto para o campo.** A Atalaia está em pré-alfa. O controlador já correu num computador em Docker, com uma placa modem no USB, caixas a sério e a consola da organização, numa bancada. A 2026-11-06 **ainda não foi testado num Raspberry Pi real**, nem num campo. Os passos de instalação abaixo seguem o guia do controlador e não foram corridos num Pi.

Conteúdo: 1. O que é o controlador · 2. Peças · 3. Preparar a placa modem · 4. Instalar o controlador · 5. Primeiro arranque: códigos e chaves · 6. Abrir a consola · 7. O relógio do controlador · 8. A rede · 9. Um controlador de reserva · 10. Cópias de segurança e durante quanto tempo se guardam os dados · 11. Atualizar o controlador e o modem · 12. Resolução de problemas

## 1. O que é o controlador

O controlador é um pequeno computador que guarda a pontuação oficial. Ouve as caixas pelo rádio, através de uma **placa modem**, e serve a **consola da organização**, uma página web que abres num telemóvel ou num portátil.

```
boxes ))) radio ((( modem board ==USB== Raspberry Pi ── Wi-Fi ── GM console, players' phones
```

## 2. Peças

| Peça | O que verificar |
| --- | --- |
| Raspberry Pi 4 ou 5 | O projeto usa um Pi 4 ou 5. Um Pi Zero 2 W está previsto para campos pequenos, não foi experimentado |
| Energia para o Pi | A fonte de alimentação oficial do teu Pi. No campo, um powerbank que dê a mesma corrente, de 10 a 20 Ah (o tamanho previsto; a autonomia não foi medida) |
| Cartão microSD | Um cartão de boa qualidade. A capacidade não é crítica |
| **Placa modem** | Uma segunda **Heltec WiFi LoRa 32 V4**, da mesma revisão (V4.3 ou V4.2) das tuas caixas, 863-928 MHz |
| Antena LoRa para o modem | 868 MHz, 2 dBi ou menos (para Taiwan, uma antena de 915-925 MHz). **Monta-a antes de a placa ter energia** |
| Cabo USB-C de dados | Curto, da placa modem ao Pi. Um cabo só de carga não funciona |
| Uma rede Wi-Fi | Um router, o ponto de acesso do telemóvel, ou uma rede feita pelo Pi. Não precisa de internet. Montar um ponto de acesso no Pi é uma tarefa normal do Raspberry Pi e não é tratada aqui. Um router de viagem está na [secção 8](#8-a-rede) |
| Uma bateria para um Pi 5 (opcional) | O relógio de tempo real do Pi 5 só mantém a hora com a bateria. Vê a [secção 7](#the-controller-clock) |

Põe a antena do modem na vertical, ao ar livre, longe de metal e do powerbank. Não a escondas numa caixa de metal. O alcance dela ainda não foi medido.

## 3. Preparar a placa modem

1. Grava a placa com a imagem do modem: transfere-a ou compila-a e escreve-a com o esptool. O caminho todo, para Windows, Linux e macOS, está em [Montar o modem de rádio](modem.md) (secções 3 e 4). Usa a mesma região das tuas caixas.
2. Liga-a ao Pi e descobre a porta (`ls /dev/ttyACM*`; [Montar o modem de rádio, secção 6](modem.md#6-ligar-ao-controlador-e-descobrir-a-porta)). O ecrã pequeno dela mostra **MODEM MODE**. Ao início diz `LINK waiting` (a língua da compilação, inglês por omissão). Está certo: o controlador ainda não está a correr. Quando o controlador arranca, o ecrã passa para a língua das tuas caixas (a definição **língua das caixas**): em português vês `LINK aguarda`, em alemão `LINK wartet`, em chinês `等待` na barra de cima. O resto deste guia usa as palavras em inglês.

O modem não tem atualização pelo ar: uma imagem nova do modem escreve-se sempre por USB ([secção 11](#update-the-controller)).

## 4. Instalar o controlador

Esta é a maneira suportada, do [guia do controlador](../../../controller/README.md#running-it): Raspberry Pi OS ou Ubuntu, os pacotes do sistema, sem Docker. Os comandos precisam de ligação à rede no Pi, e de `sudo`.

1. Instala os pacotes e o código:

   ```
   sudo apt update
   sudo apt install git python3-fastapi python3-uvicorn python3-websockets python3-paho-mqtt \
        python3-serial python3-yaml python3-cryptography libmbedtls-dev mosquitto cmake build-essential
   sudo git clone https://github.com/vakaobr/atalaia-project /opt/atalaia
   ```

   Isto traz o código mais recente (o ramo `main`). Para instalar antes uma versão publicada, corre `sudo git -C /opt/atalaia checkout v0.8.0` (a mais recente a 2026-11-06; a [página das versões](https://github.com/vakaobr/atalaia-project/releases) lista-as).
2. Compila a pequena biblioteca de programas de que o controlador precisa para os scripts dos jogos:

   ```
   sudo cmake -S /opt/atalaia/core -B /opt/atalaia/build -DATALAIA_SHARED=ON
   sudo cmake --build /opt/atalaia/build
   ```

3. Cria o utilizador e as pastas do controlador. O ficheiro de serviço do projeto espera estes nomes:

   ```
   sudo adduser --system --group --no-create-home atalaia
   sudo usermod -aG dialout atalaia
   sudo mkdir -p /etc/atalaia /var/lib/atalaia
   sudo chown atalaia /var/lib/atalaia
   sudo cp /opt/atalaia/controller/controller.example.toml /etc/atalaia/controller.toml
   ```

   O `dialout` deixa-o abrir a porta USB do modem.
4. Edita o ficheiro de definições: `sudo nano /etc/atalaia/controller.toml`. As que precisas:
   - `[modem] port`: a porta do modem. Normalmente `/dev/ttyACM0`. Para confirmar, corre `ls /dev/ttyACM*` com o modem ligado; com uma Field Box ligada também, usa o nome estável em `/dev/serial/by-id/` ([Montar o modem de rádio, secção 6](modem.md#6-ligar-ao-controlador-e-descobrir-a-porta)). Uma porta vazia quer dizer sem rádio.
   - `[radio] region`: `eu868` ou `as923-tw`. Tem de coincidir com o modem e com as caixas.
   - `[checkin] field_name`: o nome do teu campo. Quem joga vê-o. `wifi_ssid`: o nome do Wi-Fi do campo, impresso no cartaz de check-in.
   - `[api] tls_names`: os endereços que os telemóveis usam para chegar ao Pi, por exemplo `["192.168.4.1", "campo.local"]` ([secção 8](#8-a-rede)).
   - `[mqtt] enabled`: deixa como está, ou põe `false` se não usas marcadores. O valor por omissão precisa do programa Mosquitto que instalaste.
5. Instala o serviço, para arrancar quando o Pi arranca:

   ```
   sudo cp /opt/atalaia/controller/deploy/atalaia-controller.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now atalaia-controller
   ```

## 5. Primeiro arranque: códigos e chaves

1. Confirma que corre: `sudo systemctl status atalaia-controller`. Deve dizer `active (running)`. Para o registo: `sudo journalctl -u atalaia-controller -n 50`.
2. Olha para o ecrã pequeno da placa modem. **LINK OK** quer dizer que o controlador está a falar com ela. `waiting` quer dizer que não: confirma a definição da porta e o cabo. `DOWN` quer dizer que estava a falar e parou: confirma o Pi. O cabeçalho da consola deve dizer também **Rádio: ligado**. Todas as verificações, e uma entrada num jogo através do modem, estão em [Montar o modem de rádio, secções 8 e 9](modem.md#8-confirmar-que-o-controlador-e-o-modem-falam).
3. No primeiro arranque o controlador cria os segredos do campo: os dois códigos de acesso, a **chave de entrada do campo** e o certificado do próprio campo. Mostra-os. Os comandos correm na pasta do controlador, como o utilizador dele, com o ficheiro de definições dele:

   ```
   cd /opt/atalaia/controller
   sudo -u atalaia python3 -m atalaia_controller tokens --config /etc/atalaia/controller.toml
   sudo -u atalaia python3 -m atalaia_controller join-key --config /etc/atalaia/controller.toml
   ```

   Não deixes de fora o `--config`: sem ele o comando abre outra base de dados, vazia (`atalaia.db` na pasta atual), e mostra códigos novos que o controlador que está a correr não conhece. Sem `sudo -u atalaia` não consegue ler a base de dados do controlador.
4. Guarda-os em separado:
   - O **código da organização** (*GM code*) dirige o jogo: guarda-o para ti.
   - O **código só de leitura** só vigia: dá-o aos marcadores.
   - A **chave de entrada** é o segredo-mestre do campo. Não a dês a ninguém, exceto a pessoas de confiança da organização. Não a ponhas numa conversa nem num e-mail. Um controlador de reserva precisa da mesma chave ([secção 9](#standby-controller)).
5. Para um árbitro ou uma organização convidada, não dês o código da organização: cria um **código do dia** com prazo na consola (**Definições**, **Códigos de acesso temporários**; vê o [Manual da organização](game-master.md)). No Pi faz-se o mesmo com `tokens --create ETIQUETA --scope read|gm|marshals --ttl 8h` (mostrado uma só vez), `tokens --list` e `tokens --revoke ID`, com o mesmo `sudo -u atalaia ... --config /etc/atalaia/controller.toml` de cima.

## 6. Abrir a consola

1. Liga-te ao Wi-Fi do campo com um telemóvel ou um portátil.
2. Descobre o endereço do Pi: no Pi, corre `hostname -I`.
3. Abre `https://` *o endereço do Pi* `:8443/console/`, por exemplo `https://192.168.4.1:8443/console/`. O navegador avisa uma vez que não conhece o certificado: é o do próprio campo, por isso aceita-o.
4. Escreve o código da organização. (Em `http://…:8080` simples a página abre, mas a consola não envia o código: mostra o endereço https.)

O controlador serve HTTPS na porta 8443, com um certificado da autoridade do próprio campo, e o código da organização só é aceite aí. Os telemóveis verificam-no com a impressão digital do cartaz de check-in. O MQTT simples (porta 1883) é só para o próprio Pi; um marcador noutra máquina usa MQTT sobre TLS na porta 8883 (`deploy/mosquitto-tls.conf`, ver o README do controlador). Se mudares o endereço ou o nome do Pi, junta-o a `tls_names` e reinicia o serviço.

A partir daqui, segue o [Manual da organização](game-master.md): o canal de rádio, adotar as caixas, um jogo do princípio ao fim.

<a id="the-controller-clock"></a>

## 7. O relógio do controlador

Em campo não há internet, por isso o controlador não pode pedir a hora à rede. **Um Raspberry Pi 4 não tem relógio próprio.** Depois de um corte de energia arranca com a última hora que guardou (o *fake-hwclock* do sistema guarda a hora do último desligar normal ou de uma gravação de hora a hora), ou com 1 de janeiro de 1970 se não tiver nenhuma. **Um Raspberry Pi 5 tem relógio de tempo real, mas só mantém a hora com a sua bateria opcional** (a ficha da bateria do RTC); sem ela, comporta-se como um Pi 4. Se puderes, põe a bateria num Pi 5. Os telemóveis e os portáteis têm a hora certa, pelo que o controlador com o relógio errado é o que está desfasado.

### O que o controlador faz a este respeito

Os pormenores estão no [README do controlador](../../../controller/README.md#the-wall-clock).

- **Os jogos, os temporizadores e o rádio não usam o relógio.** O tempo de jogo, as pausas, os limites de tempo e os limites de ritmo correm num relógio que só conta para a frente, pelo que uma hora errada ou que salte nunca muda a duração de um jogo.
- **Repara (a guarda do relógio).** No arranque e a cada poucos segundos compara o relógio com o dia em que esta versão do programa foi publicada e com a hora mais recente que já viu (guarda-a de poucos em poucos minutos, por isso um Pi 4 que arranque com dias de atraso também é apanhado). Se o relógio estiver antes, o registo diz `the clock is wrong` e a consola mostra em todos os ecrãs uma faixa amarela **O relógio do controlador está errado.**
- **Mantém os certificados válidos.** Os certificados do campo são emitidos para um período que começa antes da data de publicação desta versão, pelo que um telemóvel com a hora certa os aceita mesmo que o relógio do controlador estivesse errado quando foram feitos. Um certificado do campo feito em 1970 por uma versão antiga (teria caducado em 1980) é substituído quando o controlador arranca; quem joga lê então o cartaz outra vez e a aplicação pede para voltar a confiar no campo.
- **Não apaga nada enquanto o relógio estiver errado**, nem durante uma hora depois de o relógio saltar um dia ou mais para a frente. Os prazos de conservação ([secção 10](#how-long-the-controller-keeps-data)) contariam, de outro modo, a partir de uma data errada.
- **Os check-ins feitos com o relógio errado têm códigos que acabam à hora errada.** Depois de acertares o relógio, um código feito em 1970 já terminou: quem joga volta a fazer o check-in (a aplicação pede).

### Acertar o relógio pela consola (correção da organização)

1. Abre a consola num telemóvel ou portátil com a hora certa.
2. Na faixa amarela, ou em **Definições › Relógio do controlador**, toca em **Acertar o relógio do controlador por este dispositivo**. Só o código da organização o permite. Com um código só de leitura aparece *Peça-se à organização do jogo que o acerte a partir da consola.*
3. A consola diz *O relógio do controlador é agora …* e a faixa desaparece.

O controlador só **avança** o relógio: recusa uma hora anterior aos dados mais recentes que guarda, anterior à sua hora atual ou (quando o relógio parece certo) mais de 14 dias à frente. Recuar deixaria os códigos de jogador e os certificados caducados voltarem a funcionar. O acerto dura até o controlador reiniciar; um Pi 4 sem bateria precisa dele depois de cada corte de energia (a faixa lembra-o).

Para manter a hora entre arranques, acerta também o relógio do sistema, como `root` no Pi: `sudo timedatectl set-time "2026-11-02 14:30:00"` (o utilizador do controlador não o consegue fazer sozinho, de propósito). Ou dá ao Pi maneira de saber a hora: um módulo RTC, a bateria do Pi 5, ou um router que dê a hora ao Pi por NTP enquanto tem internet.

Se a consola recusar («... is earlier than ...»), ou a hora do telemóvel também está errada, ou o controlador já viu uma hora posterior porque o seu relógio esteve *adiantado* durante algum tempo. O controlador nunca recua sozinho: corrige-o como `root` com `sudo timedatectl set-time` e reinicia o serviço; os registos feitos enquanto estava adiantado mantêm as suas datas.

**A partir da v0.9.0 (ainda não publicada; até lá, compila a partir do `main`)**, o controlador usa também a hora acertada nos sinais TIME que envia às caixas e em **Libertar todas as caixas que não estão neste jogo**, para que a caixa compare a hora de entrada no jogo e a libertação no mesmo relógio. Esse botão é recusado enquanto o relógio estiver errado: acerta primeiro o relógio.

Um telemóvel controlador tem a mesma guarda do relógio a partir da v0.9.0: vê o [Guia do telemóvel controlador](phone-controller.md#the-controller-clock).

## 8. A rede

Os telemóveis de quem joga, a consola e os dispositivos de jogo Android usam todos uma rede Wi-Fi no campo. Não precisa de internet. O Pi tem de estar nela, num endereço que não mude, e esse endereço tem de estar em `[api] tls_names`.

### Nomes TLS: os endereços no certificado

O certificado do campo nomeia os endereços que os telemóveis usam para chegar ao controlador. Vêm de `[api] tls_names` em `/etc/atalaia/controller.toml`, por exemplo `["192.168.8.10", "campo.local"]`.

1. Põe em `tls_names` todos os endereços e nomes que os telemóveis vão usar.
2. Reinicia o serviço: `sudo systemctl restart atalaia-controller`. O certificado passa a cobri-los.
3. Imprime outra vez o cartaz de check-in se o endereço mudou (passo 6 abaixo).

### Usar um router de viagem

Um **router de viagem** pequeno (um router de bolso ligado a uma bateria externa) é a forma mais simples de ter Wi-Fi no campo: o Pi e os telemóveis ligam-se todos ao Wi-Fi do router.

1. **Liga o Pi ao router.** O Pi liga-se ao Wi-Fi do router como um telemóvel, ou por cabo à ficha LAN (melhor: não há Wi-Fi para perder).
2. **Dá ao Pi um endereço fixo.** Nas definições do router, cria uma *reserva de DHCP* (também chamada *concessão estática* ou *associação de endereço*) para o endereço MAC do Pi, por exemplo `192.168.8.10`. Não uses um endereço diferente em cada arranque: o cartaz de check-in e os códigos QR levam o endereço do controlador. O endereço MAC vê-se no Pi com `ip link show`. (Podes definir antes um endereço estático no Pi, fora do intervalo de DHCP do router; a reserva é mais fácil de desfazer.)
3. **Diz ao controlador o seu endereço.** Põe-no em `[api] tls_names`, como acima, e reinicia o serviço.
4. **O router tem de funcionar sem internet.** Muitos routers de viagem exigem uma ligação à internet: mostram uma página de «sem internet», ou mantêm o Wi-Fi ligado mas não dão endereços enquanto não forem configurados. Testa antes do dia: desliga a ligação do router à internet (sem cabo, sem ponto de acesso), liga o router e liga um telemóvel. O telemóvel pode dizer «sem internet»; não faz mal. Se largar o Wi-Fi por não haver internet, desativa nesse telemóvel *Mudar automaticamente para dados móveis* (Android) ou *Assistência Wi-Fi* (iPhone), ou usa um router que não precise disso.
5. **NÃO deixes o router isolar os clientes.** Desliga o *isolamento do AP* / *isolamento de clientes* / *isolamento sem fios* e não ponhas os telemóveis na **rede de convidados**: as redes de convidados costumam isolar os clientes, para que os telemóveis não alcancem outros dispositivos, incluindo o Pi. Com o isolamento ligado, os telemóveis entram no Wi-Fi mas não abrem o controlador, o check-in falha e a consola não carrega. Testa: num telemóvel no Wi-Fi, abre `https://192.168.8.10:8443/console/` (o endereço reservado).
6. **O endereço que quem joga usa.** Ninguém o escreve: o **cartaz de check-in** leva o endereço https do controlador e a impressão digital no código QR. O cartaz faz-se na consola (separador **Check-in**, **Imprimir o cartaz**, ver o [Manual da organização](game-master.md)); a caixa **Endereços https do controlador** mostra os endereços que o código QR leva, um por linha, e podes corrigi-los aí (por exemplo, para o endereço reservado). Imprime-o de novo sempre que o endereço mudar. A consola também mostra o endereço a usar, quando abres por engano a página `http://` simples.

Se o intervalo de endereços do router mudar (por exemplo, é outro router no campo seguinte), o endereço reservado muda também: verifica o cartaz e `tls_names` antes do dia.

<a id="standby-controller"></a>

## 9. Um controlador de reserva

Um segundo controlador pode acompanhar um jogo e assumi-lo se o principal falhar: um segundo Pi com o seu próprio modem, ou um telemóvel Android com rádio ([Guia do telemóvel controlador](phone-controller.md#standby-controller)). Ainda não experimentado num campo.

### O que um controlador de reserva faz, e o que recusa

Enquanto está de reserva, ouve o jogo pelo seu próprio rádio, regista os eventos e acompanha o relógio e as pontuações, mas não responde a nada. A consola dele diz *Este controlador está de reserva neste jogo: acompanha o controlador principal e só manda se for promovido.* Até assumir, recusa:

- arrancar, pausar ou retomar o jogo (*Este controlador não está a mandar no jogo. Para o controlar daqui, promove-o no separador Controlador.*), convidar caixas, mudar pontuações ou ligar saídas;
- gerar dados de entrada (*Um controlador de reserva não gera dados de entrada; usa o controlador ativo.*);
- libertar caixas presas num jogo terminado: nunca reenvia o GAME_OVER sozinho e recusa **Libertar** e **Libertar todas as caixas que não estão neste jogo** (a partir da v0.9.0, ainda não publicada). Isso é com o controlador ativo.

O botão **Terminar** dele diz **Deixar o jogo**: deixa de acompanhar, e o jogo continua. Também sai sozinho quando o jogo termina.

### Montar um Pi de reserva

1. Instala o segundo Pi como nas secções 2 a 6, com a sua própria placa modem, a mesma `[radio] region` e os mesmos modos instalados que o controlador principal.
2. Dá-lhe a **mesma chave de entrada do campo**. No controlador principal, mostra-a com `join-key` ([secção 5](#5-primeiro-arranque-códigos-e-chaves)). No de reserva, põe-na em `/etc/atalaia/controller.toml`:

   ```
   [join]
   key = "<os 64 algarismos hexadecimais>"
   ```

3. Escolhe como assume o jogo, em `[controller]` (abaixo), e reinicia o de reserva: `sudo systemctl restart atalaia-controller`.
4. Para cada jogo: no controlador principal, cria o jogo. Depois abre o separador **Juntar**, em **Para** escolhe **um controlador de reserva** e toca em **Gerar**.
5. Na consola do de reserva, separador **Juntar**, **Entrar como controlador de reserva**: cola o texto e toca em **Entrar no jogo**. Diz *Este controlador está agora de reserva no jogo …*. O de reserva não pode ter nenhum jogo em curso seu.
6. Nos dois, o separador **Controlador** mostra o **Papel** (**controlador ativo** ou **de reserva**), a **Substituição** e a **Prioridade**.
7. Gera outra vez os dados de entrada e cola-os outra vez depois de mudares uma caixa de sítio, de lhe mudares a sala ou de desativares uma: o texto leva onde estão as caixas e as escolhas das balizas, para que um de reserva que assuma o jogo coloque quem joga da mesma maneira.

### `failover_mode`: manual ou automática

Em `[controller]` de `/etc/atalaia/controller.toml`:

- `failover_mode = "manual"` (por omissão): nada acontece sozinho. Quando o controlador principal deixar de responder, abre a consola do de reserva, separador **Controlador**, e toca em **Promover a controlador**. Pergunta *Este controlador passa a mandar no jogo. Continuar?*
- `failover_mode = "auto"`: o controlador principal envia o seu sinal de hora a cada 10 segundos em vez de 30. Um de reserva que falhe três seguidos (cerca de **30 segundos** de silêncio) candidata-se e, poucos segundos depois, assume o jogo. As definições de exemplo do projeto dizem para usar `auto` só depois de testes em campo, que ainda não houve.

Se o controlador antigo voltar, ouve o mais recente e passa a reserva. Dá a todos os controladores de um jogo a mesma `failover_mode`: um de reserva em `auto` conta os sinais como se viessem de 10 em 10 segundos, por isso, atrás de um principal em `manual` (um sinal a cada 30 segundos), assumiria o jogo com o principal ainda a funcionar.

### `power_source`: quem ganha quando dois se candidatam

Quando dois controladores de reserva se candidatam ao mesmo tempo, ganha o que tem melhor energia. Em `[controller]`:

| `power_source` | Significado |
| --- | --- |
| `3` (por omissão) | corrente elétrica ou alimentação USB |
| `2` | uma bateria grande (um powerbank de 10 Ah ou mais) |
| `1` | uma bateria pequena |

Põe `2` num Pi que corre a partir de um powerbank. Um telemóvel controlador conta sempre como `1`, por isso **um telemóvel a bateria cede a um Pi ligado à corrente** quando ambos se candidatam. Reinicia o controlador depois de uma mudança.

## 10. Cópias de segurança e durante quanto tempo se guardam os dados

<a id="make-a-backup"></a>

### Fazer uma cópia de segurança

Tudo o que o controlador guarda está em dois sítios: `/etc/atalaia/controller.toml` (as tuas definições) e a pasta `/var/lib/atalaia/` (a base de dados com os códigos de acesso, a chave de entrada, os jogos, as predefinições e a lista de check-in; a pasta `tls` com a autoridade de certificação do campo; a pasta `firmware` com as imagens de firmware).

1. Pára o controlador, copia e volta a iniciá-lo:

   ```
   sudo systemctl stop atalaia-controller
   sudo tar czf atalaia-backup.tar.gz /etc/atalaia /var/lib/atalaia
   sudo systemctl start atalaia-controller
   ```

2. Copia o ficheiro para uma pen USB ou para outro computador. **Trata-o como uma palavra-passe:** tem a chave de entrada, que abre todas as caixas do campo. Não o ponhas numa pasta partilhada.

Faz uma cópia antes de um dia de jogo, depois de adotares caixas novas e antes de atualizares ([secção 11](#update-the-controller)). Não copies a base de dados enquanto o controlador corre.

### Restaurar uma cópia de segurança

1. Instala um Pi novo como na secção 4.
2. Pára o serviço: `sudo systemctl stop atalaia-controller`.
3. Descompacta a cópia: `sudo tar xzf atalaia-backup.tar.gz -C /`.
4. Inicia-o: `sudo systemctl start atalaia-controller`.

As caixas continuam a funcionar, porque a chave de entrada é a mesma. Sem cópia de segurança tens de adotar todas as caixas outra vez. O restauro não foi experimentado.

Se um jogo estava a decorrer quando o controlador antigo se perdeu, as caixas podem ficar presas nele. O [Manual da organização](game-master.md#recover-from-problems) diz como as libertar.

<a id="how-long-the-controller-keeps-data"></a>

### Durante quanto tempo o controlador guarda os dados

Uma vez por dia, o controlador apaga o que é mais antigo do que os seus prazos de retenção. São definições, em dias, na secção `[checkin]` de `/etc/atalaia/controller.toml`:

| Definição | Por omissão | O que abrange |
| --- | --- | --- |
| `retention_days` | 30 (1 a 3653) | Os nomes e os números de federado dos check-ins de um jogo, apagados este número de dias depois do jogo |
| `chrono_retention_days` | 365 (30 a 3653) | As leituras do cronógrafo, as cópias de outros campos e as chaves anteriores de um marshal |
| `game_retention_days` | **90** (30 a 3653) | Os eventos, as pontuações e a lista de dispositivos de um jogo terminado. Com um servidor do site configurado, um jogo nunca é apagado antes de o servidor do site o ter por inteiro, por isso um jogo que não consegue ser enviado fica até conseguir |

Quando um jogo é apagado, os resultados das equipas ficam 365 dias, sem nenhum identificador de quem jogou.

As duas últimas também se definem na consola da organização (**Check-in › Regras do check-in**). Com `[sync] branding = "site"` vêm das definições do campo no servidor do site e a consola não as pode mudar. Depois de editares o ficheiro, reinicia o controlador (`sudo systemctl restart atalaia-controller`). Uma cópia de segurança guarda o que o controlador ainda não tinha apagado: apaga também as cópias antigas, tal como os dados.

Com um servidor do site, `[sync] push_walkins` (desligado por omissão) envia-lhe cada chegada sem inscrição como inscrição de convidado. Liga-o só depois de leres o que envia e o que o aviso de privacidade tem então de dizer: vê o [Manual da administração do site](site-admin.md).

<a id="update-the-controller"></a>

## 11. Atualizar o controlador e o modem

Atualiza entre jogos, nunca com um jogo a decorrer. Uma versão nova pode mudar a base de dados da primeira vez que arranca, por isso faz antes uma cópia de segurança: é o caminho de volta.

### Atualizar o controlador

1. Faz uma cópia de segurança ([secção 10](#make-a-backup)).
2. Obtém o código novo:

   ```
   sudo git -C /opt/atalaia fetch --tags
   sudo git -C /opt/atalaia checkout v0.8.0
   ```

   Põe a versão que queres no lugar de `v0.8.0`. Para seguir antes o código mais recente, `sudo git -C /opt/atalaia checkout main` e depois `sudo git -C /opt/atalaia pull`.
3. Instala pacotes novos, se os houver: corre outra vez a linha `sudo apt install ...` da [secção 4](#4-instalar-o-controlador) (não faz nada aos pacotes que já tens).
4. Compila outra vez a biblioteca de programas:

   ```
   sudo cmake -S /opt/atalaia/core -B /opt/atalaia/build -DATALAIA_SHARED=ON
   sudo cmake --build /opt/atalaia/build
   ```

5. Copia outra vez o ficheiro de serviço, caso tenha mudado:

   ```
   sudo cp /opt/atalaia/controller/deploy/atalaia-controller.service /etc/systemd/system/
   sudo systemctl daemon-reload
   ```

6. Procura definições novas: `diff /etc/atalaia/controller.toml /opt/atalaia/controller/controller.example.toml`. O teu ficheiro continua a funcionar sem elas (cada definição tem um valor por omissão), mas lê o que é novo.
7. Confirma as chaves das versões de firmware (abaixo).
8. Reinicia: `sudo systemctl restart atalaia-controller`, depois `sudo systemctl status atalaia-controller` e o registo, como na [secção 5](#5-primeiro-arranque-códigos-e-chaves).

Para voltar atrás, passa para a versão mais antiga, compila outra vez (passo 4) e restaura a cópia que fizeste no passo 1: uma versão mais antiga pode não ler uma base de dados que uma mais nova mudou.

### As chaves das versões de firmware

O separador **Caixas** da consola só atualiza as caixas com versões assinadas por uma chave de `[firmware] release_keys`. Desde a v0.8.0 o projeto assina com duas chaves: a raiz `424d053af5cdbc35` e a de CI `a4f6002b0122b131`. A chave de CI `32b3c815ac30ad43` foi retirada a 2026-11-04.

1. Abre `/etc/atalaia/controller.toml` e procura `[firmware]`.
2. Se `release_keys` não estiver lá, usas as chaves do projeto: não há nada a fazer.
3. Se listar chaves à mão (uma cópia de um ficheiro de exemplo antigo lista), confirma que tem estas duas e tira `rIO8ogMU3LRLLtnt6Rys+URdKYfmNv5mxvuRJQsX9Tw=` (a chave retirada), se lá estiver:

   ```
   release_keys = ["5tzPkN0AJSn+g34CP59linCRf/fcaWFc7GAAg7qzYNc=", "76eY5BoMQ4RHohhX/8iSUlIUA5o5Entfk7EFBUxpbSY="]
   ```

4. Reinicia o controlador.

Uma lista vazia (`release_keys = []`) recusa todas as versões. Atualizar as próprias caixas está no [manual da Field Box](field-box.md#update-the-boxes).

### Atualizar o modem

O modem não tem atualização pelo ar: escreve a imagem nova por USB. Quando e como fazê-lo está em [Montar o modem de rádio, Atualizar o modem](modem.md#update-the-modem). Em resumo: pára o controlador, escreve a imagem nova do modem e volta a arrancar o controlador.

Atualiza também o modem quando o registo disser `the radio modem's firmware cannot report boxes still in an ended game`, ou o separador **Caixas** da consola disser que o modem de rádio não consegue dizer que caixas ficaram num jogo terminado. Isso precisa de uma imagem do modem da v0.9.0 (ainda não publicada; até lá, compila-a a partir do `main`).

## 12. Resolução de problemas

| Problema | O que fazer |
| --- | --- |
| O ecrã do modem diz `LINK waiting` | O controlador não está a correr, ou o `[modem] port` está errado. Confirma `ls /dev/ttyACM*` e o registo do serviço. Mais na [tabela de problemas do modem](modem.md#troubleshooting) |
| `Permission denied` na porta, no registo | O utilizador não está no grupo `dialout` (secção 4, passo 3) |
| `Permission denied` ou `unable to open database file` em `/var/lib/atalaia` | A pasta não é do controlador: `sudo chown -R atalaia /var/lib/atalaia` e reinicia. Corre os comandos `tokens` e `join-key` com `sudo -u atalaia` (secção 5) |
| A consola não abre | Confirma o endereço do Pi, a porta 8443 (https) e que o telemóvel está no Wi-Fi do campo. O isolamento de clientes ou a rede de convidados de um router bloqueiam-na (secção 8) |
| A consola diz para usar o endereço https | Abriste `http://…:8080`: o controlador não aceita o código da organização por HTTP simples. Usa o endereço `https://…:8443/console/` que ela mostra |
| O navegador diz que o certificado não corresponde ao endereço | O endereço não está em `[api] tls_names`: junta-o e reinicia (secção 8) |
| Uma faixa amarela diz **O relógio do controlador está errado.** | Acerta-o pela consola (secção 7). Num Pi 4 sem bateria, depois de cada corte de energia |
| O ecrã do modem diz `RADIO FAULT` | O chip de rádio não arrancou. Experimenta outra placa; confirma a antena e o cabo |
| Uma caixa não ouve o controlador | Mesma região e mesmo canal? Antenas montadas? Vê o [Manual da organização](game-master.md#recover-from-problems) |
| Uma caixa ficou presa num jogo terminado, e a consola diz que o modem de rádio não o consegue dizer | A imagem do modem é anterior à v0.9.0: atualiza-a (secção 11). Até lá, tira a caixa do jogo na própria caixa ([manual da Field Box](field-box.md#take-a-box-out-of-its-game)) |
| Não aparece **Promover a controlador**, ou o de reserva nunca assume | O de reserva não entrou neste jogo (secção 9, passos 4 e 5), ou a `failover_mode` é `manual`: promove-o à mão |
| Esqueci-me dos códigos | Corre outra vez os comandos `tokens` e `join-key` (secção 5) |

Encontraste um passo que não corresponde? Abre uma issue ou diz-nos nas [Discussions](https://github.com/vakaobr/atalaia-project/discussions).
