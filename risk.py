from datetime import date


def assess_risk(crop, weather, predicted, reliability=0.8):

    score = 0.1
    reasons = []

    # 1. Weather risk analysis
    rain = float(weather.get("rainfall", 800))
    temp = float(weather.get("temperature", 28))

    if rain < 400:
        score += 0.25
        reasons.append("Severe low rainfall - drought risk")
    elif rain < 600:
        score += 0.1
        reasons.append("Low rainfall risk")
    elif rain > 1500:
        score += 0.2
        reasons.append("Excess rainfall - flood and disease risk")
    elif rain > 1200:
        score += 0.1
        reasons.append("High rainfall risk")

    if temp > 38:
        score += 0.2
        reasons.append("Severe heat stress")
    elif temp > 32:
        score += 0.1
        reasons.append("Moderate heat stress")
    elif temp < 10:
        score += 0.15
        reasons.append("Cold stress")

    # 2. Irrigation risk
    irrigation = str(crop.get("irrigation", "")).lower()

    if irrigation in ("none", "rainfed", ""):
        score += 0.1
        reasons.append("No irrigation backup")

    # 3. Farmer reliability
    if reliability is not None and float(reliability) < 0.6:
        score += 0.15
        reasons.append("Low farmer delivery reliability")

    # 4. Harvest delay analysis
    delay = 0
    expected = crop.get("expected_harvest_date")
    actual = predicted.get("harvest_date")

    if expected and actual:
        expected_date = date.fromisoformat(str(expected)[:10])
        actual_date = date.fromisoformat(str(actual)[:10])

        delay = (actual_date - expected_date).days

        if delay > 7:
            score += 0.25
            reasons.append(f"Severe harvest delay of {delay} days")
        elif delay >= 3:
            score += 0.1
            reasons.append(f"Possible harvest delay of {delay} days")

    # 5. Final risk classification
    score = round(min(score, 1.0), 2)

    if score >= 0.6:
        level = "HIGH"
        rec = "High risk. Arrange backup supply and contact the farmer immediately."
    elif score >= 0.35:
        level = "MEDIUM"
        rec = "Moderate risk. Monitor weather and contact the farmer regularly."
    else:
        level = "LOW"
        rec = "On track. Keep regular monitoring."

    if reasons:
        rec += " Risk factors: " + "; ".join(reasons) + "."

    return {
        "risk_score": score,
        "risk_level": level,
        "risk_factors": reasons,
        "harvest_delay_days": delay,
        "recommendation": rec
    }
