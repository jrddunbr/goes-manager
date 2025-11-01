# Goes Manager

A comprehensive system for managing GOES (Geostationary Operational Environmental Satellite) data lifecycles, including monitoring, retention, and health alerting.

## Purpose

GoesManager is designed to help efficiently manage large volumes of GOES satellite data. The system provides automated tools for:

- **Filesystem Monitoring**: Track and monitor GOES data files as they arrive and are processed
- **Health Monitoring**: Alert on system health issues and data processing anomalies, including monitoring of satellite feed signal and decoder health
- **Retention Management**: Use flexible data lifecycle policies to optimize storage usage, including moving files, compression with gzip/zstd, and deletion

## Components

The system consists of several Python modules:

- **goes_filesystem_monitor**: Monitors filesystem for GOES data changes
- **goes_health_monitor**: Tracks system health and sends alerts
- **goes_retention**: Implements data retention policies and cleanup
- **goes_manager**: Core library utilities and configuration management

## Getting Started

### Prerequisites

- Python 3.13.7 or compatible version (Earlier versions may work, but are not tested)
- virtualenv for package management (optional)

This project is specifically designed with the following use case in mind:

* Raspberry Pi 5 running stock Raspbian OS plus `python3-zstandard` and `python3-systemd` packages
* 1TB SSD for data storage
* nginx server for file sharing on the internet (forward the connection as appropriate)
* RTLSDR v3 with bias tee connected to a [Discovery Dish](https://www.crowdsupply.com/krakenrf/discovery-dish) configured for a GOES satellite (GOES East in my case)

### Installation

1. Clone the repository
2. Set up the virtual environment:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt  # if available
   ```

### Configuration

Configuration files are located in the `config/` directory. Sample configurations are provided:

- `common.sample.json` - Common settings
- `filesystem_monitor.sample.json` - Filesystem monitoring configuration
- `health_monitor.sample.json` - Health monitoring settings
- `retention.sample.json` - Retention policy definitions

Copy the sample files and customize them for your environment:
```bash
cp config/common.sample.json config/common.json
# Edit config/common.json with your settings
```
### Running the Services

Each component can be run as a standalone service or via systemd:

**Manual execution:**
```bash
python -m goes_filesystem_monitor
python -m goes_health_monitor
python -m goes_retention
```
**Systemd services:**
```bash
sudo cp systemd/*.service systemd/*.timer /etc/systemd/system/
sudo systemctl enable goes-filesystem-monitor.service
sudo systemctl start goes-filesystem-monitor.service
```
## Documentation

Comprehensive documentation is available in the `docs/` directory:

- [Software Components](docs/software/index.md)

These outline the GOES data products (and the services we are building on top of them):

- [GOES Imagery](docs/goes-imagery.md)
- [EMWIN Products](docs/emwin.md)
- [Retention Policies](docs/retention.md)
- [Admin Messages](docs/admin-messages.md)

## Contributing

Contributions are welcome! To contribute:

1. **Fork the repository** on GitHub and clone your fork to your local machine.
2. **Follow the existing code structure** - each service is modular with its own package
3. **Update documentation** in the `docs/` directory for new features. 
    * This helps facilitate AI code generation, as well as human project planning
4. **Test your changes** before submitting
5. **Submit a pull request** with a clear description of your changes

## Future Work

### Planned Enhancements

- **Dashboard Integration**: Real-time web dashboard for monitoring GOES data streams and system health
- **Derivative Publisher**: Automated generation and publishing of derived products from raw GOES data eg. timelapse animations, localized weather reports, etc.
- **Timelapse Generator**: Automated creation of timelapse animations from GOES imagery sequences
- **API Layer**: RESTful API for programmatic access to monitoring and management functions with tools such as HomeAssistant

## License

See [LICENSE](LICENSE) file; standard MIT license.

## Support

For documentation and guides, see the `docs/` directory. For issues and questions, please use the project's issue tracker on GitHub.
```
