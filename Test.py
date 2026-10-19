import predict


result = predict.generate_forecast(
    forecast_period_days=14,
    promo=1,
    promo2=1,
    state_holiday_label="None",
    school_holiday=0,
    competition_distance=3200,
)

print(result)