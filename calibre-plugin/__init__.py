from calibre.customize import InterfaceActionBase


class EpubTranslatePlugin(InterfaceActionBase):
    name = "Epub Translate"
    description = "Translate selected EPUB books into bilingual editions and add them to the library"
    supported_platforms = ["osx", "windows", "linux"]
    author = "yubai"
    version = (1, 0, 0)
    minimum_calibre_version = (5, 0, 0)

    actual_plugin = "calibre_plugins.epub_translate.ui:EpubTranslateAction"

    def is_customizable(self):
        return True

    def config_widget(self):
        from calibre_plugins.epub_translate.config import ConfigWidget
        return ConfigWidget()

    def save_settings(self, config_widget):
        config_widget.save_settings()
