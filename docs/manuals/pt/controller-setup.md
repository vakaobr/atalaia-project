<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Guia de montagem do controlador (Raspberry Pi)

Para quem na organização monta o **controlador de campo** num Raspberry Pi. Precisas de saber escrever comandos num terminal. Não precisas de escrever código. Os pormenores para quem desenvolve estão no [guia do controlador](../../../controller/README.md) (em inglês). Dirigir o jogo está no [Manual da organização](game-master.md). Em inglês: [Controller setup guide](../en/controller-setup.md).

> **Ainda não está pronto para o campo.** A Atalaia está em pré-alfa. O controlador já correu num computador em Docker, com uma placa modem no USB, uma caixa a sério e a consola da organização, numa bancada. **Ainda não testado num Raspberry Pi real**, nem num campo. Os passos de instalação abaixo seguem o guia do controlador e não foram corridos num Pi.

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
| Uma rede Wi-Fi | Um router, o ponto de acesso do telemóvel, ou uma rede feita pelo Pi. Não precisa de internet. Montar um ponto de acesso no Pi é uma tarefa normal do Raspberry Pi e não é tratada aqui |

Põe a antena do modem na vertical, ao ar livre, longe de metal e do powerbank. Não a escondas numa caixa de metal. O alcance dela ainda não foi medido.

## 3. Preparar a placa modem

1. Grava a placa com a imagem do modem: transfere-a ou compila-a e escreve-a com o esptool. O caminho todo, para Windows, Linux e macOS, está em [Montar o modem de rádio](modem.md) (secções 3 e 4). Usa a mesma região das tuas caixas.
2. Liga-a ao Pi e descobre a porta (`ls /dev/ttyACM*`; [Montar o modem de rádio, secção 6](modem.md#6-ligar-ao-controlador-e-descobrir-a-porta)). O ecrã pequeno dela mostra **MODEM MODE**. Ao início diz `LINK waiting` (a língua da compilação, inglês por omissão). Está certo: o controlador ainda não está a correr. Quando o controlador arranca, o ecrã passa para a língua das tuas caixas (a definição **língua das caixas**): em português vês `LINK aguarda`, em alemão `LINK wartet`, em chinês `等待` na barra de cima. O resto deste guia usa as palavras em inglês.

## 4. Instalar o controlador

Esta é a maneira suportada, do [guia do controlador](../../../controller/README.md#running-it): Raspberry Pi OS ou Ubuntu, os pacotes do sistema, sem Docker. Os comandos precisam de ligação à rede no Pi, e de `sudo`.

1. Instala os pacotes e o código:

   ```
   sudo apt update
   sudo apt install git python3-fastapi python3-uvicorn python3-websockets python3-paho-mqtt \
        python3-serial python3-yaml python3-cryptography libmbedtls-dev mosquitto cmake build-essential
   sudo git clone https://github.com/vakaobr/atalaia-project /opt/atalaia
   ```

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
   - `[api] tls_names`: os endereços que os telemóveis usam para chegar ao Pi, por exemplo `["192.168.4.1", "campo.local"]`.
   - `[mqtt] enabled`: deixa como está, ou põe `false` se não usas marcadores. O valor por omissão precisa do programa Mosquitto que instalaste.
5. Instala o serviço, para arrancar quando o Pi arranca:

   ```
   sudo cp /opt/atalaia/controller/deploy/atalaia-controller.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now atalaia-controller
   ```

## 5. Primeiro arranque

1. Confirma que corre: `sudo systemctl status atalaia-controller`. Deve dizer `active (running)`. Para o registo: `sudo journalctl -u atalaia-controller -n 50`.
2. Olha para o ecrã pequeno da placa modem. **LINK OK** quer dizer que o controlador está a falar com ela. `waiting` quer dizer que não: confirma a definição da porta e o cabo. `DOWN` quer dizer que estava a falar e parou: confirma o Pi. O cabeçalho da consola deve dizer também **Rádio: ligado**. Todas as verificações, e uma entrada num jogo através do modem, estão em [Montar o modem de rádio, secções 8 e 9](modem.md#8-confirmar-que-o-controlador-e-o-modem-falam).
3. No primeiro arranque o controlador cria os segredos do campo: os dois códigos de acesso, a **chave de entrada do campo** e o certificado do próprio campo. Mostra-os. O comando corre na pasta do controlador, como o utilizador dele:

   ```
   cd /opt/atalaia/controller
   sudo -u atalaia python3 -m atalaia_controller tokens --config /etc/atalaia/controller.toml
   sudo -u atalaia python3 -m atalaia_controller join-key --config /etc/atalaia/controller.toml
   ```

   O **código da organização** (*GM code*) dirige o jogo: guarda-o para ti. O **código só de leitura** só vigia: dá-o aos marcadores. A **chave de entrada** é o segredo-mestre do campo. Não a dês a ninguém, exceto a pessoas de confiança da organização. Não a ponhas numa conversa nem num e-mail.

## 6. Abrir a consola

1. Liga-te ao Wi-Fi do campo com um telemóvel ou um portátil.
2. Descobre o endereço do Pi: no Pi, corre `hostname -I`.
3. Abre `https://` *o endereço do Pi* `:8443/console/`, por exemplo `https://192.168.4.1:8443/console/`. O navegador avisa uma vez que não conhece o certificado: é o do próprio campo, por isso aceita-o. Escreve o código da organização. (Em `http://…:8080` simples a página abre, mas a consola não envia o código: mostra o endereço https.)

O controlador serve HTTPS na porta 8443, com um certificado da autoridade do próprio campo, e o código da organização só é aceite aí. Os telemóveis verificam-no com a impressão digital do cartaz de check-in. O MQTT simples (porta 1883) é só para o próprio Pi; um marcador noutra máquina usa MQTT sobre TLS na porta 8883 (`deploy/mosquitto-tls.conf`, ver o README do controlador). Se mudares o endereço ou o nome do Pi, junta-o a `tls_names` e reinicia o serviço.

A partir daqui, segue o [Manual da organização](game-master.md): o canal de rádio, adotar as caixas, um jogo do princípio ao fim.

## O relógio

Em campo não há internet, por isso o controlador não pode pedir a hora à rede. **Um Raspberry Pi 4 não tem relógio próprio.** Depois de um corte de energia arranca com a última hora que guardou (o *fake-hwclock* do sistema guarda a hora do último desligar normal ou de uma gravação de hora a hora), ou com 1 de janeiro de 1970 se não tiver nenhuma. **Um Raspberry Pi 5 tem relógio de tempo real, mas só mantém a hora com a sua bateria opcional** (a ficha da bateria do RTC); sem ela, comporta-se como um Pi 4. Se for possível, ponha-se a bateria num Pi 5. Os telemóveis e os portáteis têm a hora certa, pelo que o controlador com o relógio errado é o que está desfasado.

O que o controlador faz a este respeito (os pormenores estão no [README do controlador](../../../controller/README.md#the-wall-clock)):

- **Os jogos, os temporizadores e o rádio não usam o relógio.** O tempo de jogo, as pausas, os limites de tempo e os limites de ritmo correm num relógio que só conta para a frente, pelo que uma hora errada ou que salte nunca muda a duração de um jogo.
- **Repara.** No arranque e a cada poucos segundos compara o relógio com o dia em que esta versão do programa foi publicada e com a hora mais recente que já viu (guarda-a de poucos em poucos minutos, por isso um Pi 4 que arranque com dias de atraso também é apanhado). Se o relógio estiver antes, o registo diz `the clock is wrong` e a consola mostra em todos os ecrãs uma faixa amarela **O relógio do controlador está errado**.
- **Mantém os certificados válidos.** Os certificados do campo são emitidos para um período que começa antes da data de publicação desta versão, pelo que um telemóvel com a hora certa os aceita mesmo que o relógio do controlador estivesse errado quando foram feitos. Um certificado do campo feito em 1970 por uma versão antiga (teria caducado em 1980) é substituído quando o controlador arranca; os jogadores leem então o cartaz outra vez e a aplicação pede para voltar a confiar no campo.
- **Não apaga nada enquanto o relógio estiver errado**, nem durante uma hora depois de o relógio saltar um dia ou mais para a frente. Os prazos de conservação (ver [Durante quanto tempo o controlador guarda os dados](#durante-quanto-tempo-o-controlador-guarda-os-dados)) contariam, de outro modo, a partir de uma data errada.
- **Os check-ins feitos com o relógio errado têm códigos que acabam à hora errada.** Depois de se acertar o relógio, um código feito em 1970 já terminou: os jogadores voltam a fazer o check-in (a aplicação pede).

**Para acertar o relógio**, abra-se a consola num telemóvel ou portátil (a hora destes está certa) e, na faixa amarela ou em **Definições › Relógio do controlador**, toque-se em **Acertar o relógio do controlador por este dispositivo**. Só o código da organização do jogo o permite. O controlador só **avança** o relógio: recusa uma hora anterior aos dados mais recentes que guarda, anterior à sua hora atual ou (quando o relógio parece certo) mais de 14 dias à frente. Recuar deixaria os códigos de jogador e os certificados caducados voltarem a funcionar. O acerto dura até o Pi reiniciar; um Pi 4 sem bateria precisa dele depois de cada corte de energia (a faixa lembra-o). Para manter a hora entre arranques, acerta-se também o relógio do sistema, como `root` no Pi: `sudo timedatectl set-time "2026-11-02 14:30:00"` (o utilizador do controlador não o consegue fazer sozinho, de propósito), ou dá-se ao Pi maneira de saber a hora: um módulo RTC, a bateria do Pi 5, ou um router que dê a hora ao Pi por NTP enquanto tem internet.

Se a consola recusar («... is earlier than ...»), ou a hora do telemóvel também está errada, ou o controlador já viu uma hora posterior porque o seu relógio esteve *adiantado* durante algum tempo. O controlador nunca recua sozinho: corrija-se como `root` com `sudo timedatectl set-time` e reinicie-se o serviço; os registos feitos enquanto estava adiantado mantêm as suas datas.

**Um telemóvel controlador faz o mesmo.** A hora de um telemóvel costuma estar certa, dada pela rede móvel, mas pode estar errada num telemóvel que foi reposto, acertado à mão ou que esteve muito tempo sem rede. O telemóvel controlador verifica-a da mesma maneira (a data desta versão, a hora mais recente que já viu, os dados mais recentes que guarda), mostra a mesma faixa amarela, adia as eliminações da mesma maneira e aceita o mesmo **Acertar o relógio do controlador por este dispositivo**, só para a frente. O acerto dura até o controlador parar. O controlador usa também esta hora acertada quando diz a hora às caixas e quando envia **Libertar todas as caixas que não estão neste jogo**, para que a caixa compare as duas no mesmo relógio.

## Usar um router de viagem

Um **router de viagem** pequeno (um router de bolso ligado a uma bateria externa) é a forma mais simples de ter Wi-Fi no campo: o Pi e os telemóveis ligam-se todos ao Wi-Fi do router.

1. **Ligar o Pi ao router.** O Pi liga-se ao Wi-Fi do router como um telemóvel, ou por cabo à ficha LAN (melhor: não há Wi-Fi para perder).
2. **Dar ao Pi um endereço fixo.** Nas definições do router, crie-se uma *reserva de DHCP* (também chamada *concessão estática* ou *associação de endereço*) para o endereço MAC do Pi, por exemplo `192.168.8.10`. Não se use um endereço diferente em cada arranque: o cartaz de check-in e os códigos QR levam o endereço do controlador. O endereço MAC vê-se no Pi com `ip link show`. (Pode definir-se antes um endereço estático no Pi, fora do intervalo de DHCP do router; a reserva é mais fácil de desfazer.)
3. **Dizer ao controlador o seu endereço.** Ponha-se em `[api] tls_names` no `/etc/atalaia/controller.toml`, por exemplo `["192.168.8.10", "campo.local"]`, e reinicie-se o serviço, para o certificado o cobrir (secção 6).
4. **O router tem de funcionar sem internet.** Muitos routers de viagem exigem uma ligação à internet: mostram uma página de «sem internet», ou mantêm o Wi-Fi ligado mas não dão endereços enquanto não forem configurados. Teste-se antes do dia: desligue-se a ligação do router à internet (sem cabo, sem ponto de acesso), ligue-se o router e ligue-se um telemóvel. O telemóvel pode dizer «sem internet»; não faz mal. Se largar o Wi-Fi por não haver internet, desative-se nesse telemóvel *Mudar automaticamente para dados móveis* (Android) ou *Assistência Wi-Fi* (iPhone), ou use-se um router que não precise disso.
5. **NÃO deixar o router isolar os clientes.** Desligue-se o *isolamento do AP* / *isolamento de clientes* / *isolamento sem fios* e não se ponham os telemóveis na **rede de convidados**: as redes de convidados costumam isolar os clientes, para que os telemóveis não alcancem outros dispositivos, incluindo o Pi. Com o isolamento ligado, os telemóveis entram no Wi-Fi mas não abrem o controlador, o check-in falha e a consola não carrega. Teste-se: num telemóvel no Wi-Fi, abra-se `https://192.168.8.10:8443/console/` (o endereço reservado).
6. **O endereço que os jogadores usam.** Os jogadores não o escrevem: o **cartaz de check-in** leva o endereço https do controlador e a impressão digital no código QR. O cartaz faz-se na consola (separador **Check-in**, **Imprimir o cartaz**, ver o [Manual da organização do jogo](game-master.md#regras-do-check-in-e-o-cartaz)); a caixa **Endereços https do controlador** mostra os endereços que o código QR leva, um por linha, e pode corrigi-los aí (por exemplo, para o endereço reservado). Imprima-se de novo sempre que o endereço mudar. A consola também mostra o endereço a usar, quando se abre por engano a página `http://` simples.

Se o intervalo de endereços do router mudar (por exemplo, é outro router no campo seguinte), o endereço reservado muda também: verifiquem-se o cartaz e `tls_names` antes do dia.

## 7. Cópias de segurança

Tudo o que o controlador guarda está em dois sítios: `/etc/atalaia/controller.toml` (as tuas definições) e a pasta `/var/lib/atalaia/` (a base de dados com os códigos de acesso, a chave de entrada, os jogos, as predefinições e a lista de check-in; a pasta `tls` com a autoridade de certificação do campo; a pasta `firmware` com as imagens de firmware).

Para fazer uma cópia de segurança, pára o controlador, copia e volta a iniciá-lo:

```
sudo systemctl stop atalaia-controller
sudo tar czf atalaia-backup.tar.gz /etc/atalaia /var/lib/atalaia
sudo systemctl start atalaia-controller
```

Copia o ficheiro para uma pen USB ou para outro computador. **Trata-o como uma palavra-passe:** tem a chave de entrada, que abre todas as caixas do campo. Não o ponhas numa pasta partilhada.

Para restaurar num Pi novo, instala como na secção 4, pára o serviço, descompacta a cópia com `sudo tar xzf atalaia-backup.tar.gz -C /` e inicia-o. As caixas continuam a funcionar, porque a chave de entrada é a mesma. Sem cópia de segurança tens de adotar todas as caixas outra vez. O restauro não foi experimentado.

Faz uma cópia antes de um dia de jogo e depois de adotares caixas novas. Não copies a base de dados enquanto o controlador corre.

### Durante quanto tempo o controlador guarda os dados

Uma vez por dia, o controlador apaga o que é mais antigo do que os seus prazos de retenção. São definições, em dias, na secção `[checkin]` de `/etc/atalaia/controller.toml`:

- `retention_days = 30`: os nomes e os números de federado dos check-ins de um jogo, apagados este número de dias depois do jogo.
- `chrono_retention_days = 365` (30 a 3653): as leituras do cronógrafo, as cópias de outros campos e as chaves anteriores de um marshal.
- `game_retention_days = 365` (30 a 3653): os eventos, as pontuações e a lista de dispositivos de um jogo terminado. Com um servidor do site configurado, um jogo nunca é apagado antes de o servidor do site o ter por inteiro, por isso um jogo que não consegue ser enviado fica até conseguir.

As duas últimas também se definem na consola do GM (**Check-in › Regras do check-in**, ver o [manual da organização](game-master.md#regras-do-check-in-e-o-cartaz)). Com `[sync] branding = "site"` vêm das definições do campo no servidor do site e a consola não as pode mudar. Depois de editares o ficheiro, reinicia o controlador (`sudo systemctl restart atalaia-controller`). Uma cópia de segurança guarda o que o controlador ainda não tinha apagado: apaga também as cópias antigas, tal como os dados.

**Chegadas sem inscrição no servidor do site.** Com um servidor do site, depois de um jogo feito a partir de um jogo agendado o controlador envia só quantas pessoas vieram sem inscrição. Põe `push_walkins = true` em `[sync]` para enviar também cada uma delas, como inscrição de convidado: o identificador de participante, o nome dado no check-in e os resultados de cronógrafo das réplicas declaradas (tipo, classe, passou ou recusada). Nunca envia número de federado, equipa, marca e modelo de réplica nem bilhete, e marshals e GM não são enviados. O servidor do site apaga estas inscrições de convidado 30 dias depois do jogo, e logo que o controlador apague essa pessoa a pedido dela. Vem desligado por omissão. Liga-o só se o campo precisar das chegadas sem inscrição nos seus registos do site, e di-lo no aviso de privacidade do campo (o modelo tem linhas para isso, marcadas como escolha do campo e para revisão por um advogado). O aviso de check-in que a app mostra por omissão diz que o nome nunca é enviado ao servidor do site: com isto ligado, dá ao controlador o teu próprio aviso de check-in (`[checkin] notice_pt` e `notice_en`, ficheiros em Markdown) que diga o contrário, e sobe o `notice_version`. Um servidor do site que ainda não conheça convidados recebe só o número. No controlador do telemóvel, a mesma definição é **Enviar as chegadas sem inscrição ao servidor do site como convidados**, nas definições do site.

## 8. Resolução de problemas

| Problema | O que fazer |
| --- | --- |
| O ecrã do modem diz `LINK waiting` | O controlador não está a correr, ou o `[modem] port` está errado. Confirma `ls /dev/ttyACM*` e o registo do serviço. Mais na [tabela de problemas do modem](modem.md#10-resolução-de-problemas) |
| `Permission denied` na porta, no registo | O utilizador não está no grupo `dialout` (secção 4, passo 3) |
| A consola não abre | Confirma o endereço do Pi, a porta 8443 (https) e que o telemóvel está no Wi-Fi do campo |
| A consola diz para usar o endereço https | Abriste `http://…:8080`: o controlador não aceita o código da organização por HTTP simples. Usa o endereço `https://…:8443/console/` que ela mostra |
| O ecrã do modem diz `RADIO FAULT` | O chip de rádio não arrancou. Experimenta outra placa; confirma a antena e o cabo |
| Uma caixa não ouve o controlador | Mesma região e mesmo canal? Antenas montadas? Vê a resolução de problemas do Manual da organização |
| Esqueci-me dos códigos | Corre outra vez os comandos `tokens` e `join-key` (secção 5) |

Encontraste um passo que não corresponde? Abre uma issue ou diz-nos nas [Discussions](https://github.com/vakaobr/atalaia-project/discussions).
