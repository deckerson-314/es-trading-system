# Trading Strategy Web Dashboards

This directory contains all HTML dashboards for the trading strategy system.

## Files

- **index.html** - Landing page with links to all dashboards
- **ib_deployment_dashboard.html** - Live trading dashboard (updated in real-time)
- **ga_dashboard_v3.html** - Genetic algorithm optimization results
- **comprehensive_dashboard_v3.0.html** - Backtest analysis results

## Starting the Web Server

Run from the project root:

```bash
python start_web_server.py
```

This will:
- Start a local web server on port 8000
- Automatically detect and start ngrok if installed
- Open the landing page in your browser

## Access URLs

- **Local**: http://127.0.0.1:8000
- **Network**: http://<your-ip>:8000
- **Public (ngrok)**: Check console output for ngrok URL

## Notes

- The landing page auto-refreshes every 30 seconds
- Live trading dashboard updates every 10 seconds
- All dashboards are automatically copied here when generated

