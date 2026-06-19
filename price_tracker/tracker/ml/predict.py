def predict_next_price(product_id):
    import torch
    from .lstm_model import train_lstm
    result = train_lstm(product_id)

    if not result:
        return {
            "predicted_price": None,
            "decision": "Not enough data"
        }

    model, scaler, prices_scaled = result

    last_5 = prices_scaled[-5:]
    last_5 = last_5.reshape(1, 5, 1)

    model.eval()
    with torch.no_grad():
        last_5_t = torch.tensor(last_5, dtype=torch.float32)
        next_scaled = model(last_5_t).numpy()

    next_price = scaler.inverse_transform(next_scaled)[0][0]
    current_price = scaler.inverse_transform([prices_scaled[-1]])[0][0]

    decision = "HOLD"
    if next_price < current_price:
        decision = "BUY 📉"
    elif next_price > current_price:
        decision = "WAIT 📈"

    return {
        "predicted_price": round(float(next_price), 2),
        "decision": decision
    }
