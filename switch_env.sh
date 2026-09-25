#!/bin/bash

# URLs fijas del proyecto
URL_RENDER="https://bot-gastos-moy7.onrender.com/webhook"
URL_LOCAL="https://translate-punk-jokingly.ngrok-free.dev/webhook"
DOMAIN_NGROK="translate-punk-jokingly.ngrok-free.dev"

# Asegurar perfil activo de Twilio
export TWILIO_PROFILE="bot-gastos"

echo "=========================================="
echo "    CAMBIAR ENTORNO SANDBOX DE TWILIO"
echo "=========================================="
echo "1) Producción (Render)"
echo "2) Local (Mac / VS Code + ngrok)"
read -p "Selecciona una opción [1 o 2]: " opcion

if [ "$opcion" == "1" ]; then
    echo "🌐 Apuntando Twilio Sandbox a Render..."
    
    # Actualización directa del número de la Sandbox (+14155238886)
    twilio api:core:incoming-phone-numbers:update \
      --phone-number "+14155238886" \
      --sms-url "$URL_RENDER" 2>/dev/null || \
    twilio api:messaging:v1:services:phone-numbers:update \
      --phone-number "+14155238886" \
      --capabilities-whatsapp true \
      --sms-url "$URL_RENDER" 2>/dev/null

    pkill -f ngrok 2>/dev/null
    echo "✅ ¡Listo! Configuración enviada a RENDER."

elif [ "$opcion" == "2" ]; then
    if pgrep -x "ngrok" > /dev/null; then
        echo "⚡ ngrok ya se está ejecutando."
    else
        echo "🚀 Iniciando ngrok en segundo plano..."
        nohup ngrok http --url=$DOMAIN_NGROK 5000 > /dev/null 2>&1 &
        sleep 2
    fi

    echo "💻 Apuntando Twilio Sandbox a Local ($URL_LOCAL)..."
    
    # Actualización directa del número de la Sandbox (+14155238886)
    twilio api:core:incoming-phone-numbers:update \
      --phone-number "+14155238886" \
      --sms-url "$URL_LOCAL" 2>/dev/null || \
    twilio api:messaging:v1:services:phone-numbers:update \
      --phone-number "+14155238886" \
      --capabilities-whatsapp true \
      --sms-url "$URL_LOCAL" 2>/dev/null

    echo "✅ ¡Listo! Configuración enviada a tu MAC."

else
    echo "❌ Opción no válida."
fi