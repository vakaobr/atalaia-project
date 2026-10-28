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

1. Compila o firmware do modem e grava a placa. Os passos estão no [guia do firmware, secção 9](firmware.md#9-a-placa-modem). Usa a mesma região das tuas caixas.
2. Liga-a ao Pi. O ecrã pequeno dela mostra **MODEM MODE**. Ao início diz `LINK waiting` (a língua da compilação, inglês por omissão). Está certo: o controlador ainda não está a correr. Quando o controlador arranca, o ecrã passa para a língua das tuas caixas (a definição **língua das caixas**): em português vês `LINK aguarda`, em alemão `LINK wartet`, em chinês `等待` na barra de cima. O resto deste guia usa as palavras em inglês.

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
   - `[modem] port`: a porta do modem. Normalmente `/dev/ttyACM0`. Para confirmar, corre `ls /dev/ttyACM*` com o modem ligado.
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
2. Olha para o ecrã pequeno da placa modem. **LINK OK** quer dizer que o controlador está a falar com ela. `waiting` quer dizer que não: confirma a definição da porta e o cabo. `DOWN` quer dizer que estava a falar e parou: confirma o Pi.
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
3. Abre `http://` *o endereço do Pi* `:8080/console/`, por exemplo `http://192.168.4.1:8080/console/`. Escreve o código da organização.

O controlador serve também HTTPS na porta 8443, com um certificado da autoridade do próprio campo. Os telemóveis verificam-no com a impressão digital do cartaz de check-in. Se mudares o endereço ou o nome do Pi, junta-o a `tls_names` e reinicia o serviço.

A partir daqui, segue o [Manual da organização](game-master.md): o canal de rádio, adotar as caixas, um jogo do princípio ao fim.

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

## 8. Resolução de problemas

| Problema | O que fazer |
| --- | --- |
| O ecrã do modem diz `LINK waiting` | O controlador não está a correr, ou o `[modem] port` está errado. Confirma `ls /dev/ttyACM*` e o registo do serviço |
| `Permission denied` na porta, no registo | O utilizador não está no grupo `dialout` (secção 4, passo 3) |
| A consola não abre | Confirma o endereço do Pi, a porta 8080 e que o telemóvel está no Wi-Fi do campo |
| O ecrã do modem diz `RADIO FAULT` | O chip de rádio não arrancou. Experimenta outra placa; confirma a antena e o cabo |
| Uma caixa não ouve o controlador | Mesma região e mesmo canal? Antenas montadas? Vê a resolução de problemas do Manual da organização |
| Esqueci-me dos códigos | Corre outra vez os comandos `tokens` e `join-key` (secção 5) |

Encontraste um passo que não corresponde? Abre uma issue ou diz-nos nas [Discussions](https://github.com/vakaobr/atalaia-project/discussions).
