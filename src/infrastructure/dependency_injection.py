from dependency_injector import containers, providers


class DependencyInjection(containers.DeclarativeContainer):
    config = providers.Configuration()
