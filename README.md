# ReportLabDMA

**ReportLabDMA** é uma aplicação desktop desenvolvida em Python para agilizar todo o fluxo de trabalho de inspeções de campo, desde a organização de fotos georreferenciadas até a geração de relatórios completos em HTML e PDF.

---

## Visão Geral

Em vistorias de campo, é comum lidar com dezenas ou centenas de imagens: renomear arquivos, agrupar por área, adicionar anotações e, enfim, compilar tudo em relatórios formais. O ReportLabDMA automatiza cada etapa desse processo, garantindo padronização, rastreabilidade e economia de tempo.

Principais objetivos:

- **Organização Automática:** renomeação e classificação de imagens com base em metadados (EXIF e coordenadas GPS).  
- **Análise Geoespacial:** associação das fotos a quadras e canteiros definidos em mapas GeoJSON.  
- **Anotações e Macros:** marcação de status e inserção de comentários padronizados por imagem.  
- **Relatórios Profissionais:** geração de relatórios PDF e HTML com layout customizável.

---

## Funcionalidades Detalhadas

### 1. Processamento de Imagens
- **Metadados EXIF:** extração de data/hora, GPS, orientação e outros dados relevantes.  
- **Cálculo de Hash MD5:** identificação única de cada foto para evitar duplicatas.  
- **Mapeamento Geoespacial:** algoritmo que cruza coordenadas GPS da imagem com polígonos de `map.geojson` para determinar a quadra e canteiro correspondente.  
- **Cache de Miniaturas:** gera e armazena miniaturas em Base64, acelerando carregamentos subsequentes.

### 2. Geração de Relatórios
- **HTML Personalizado:** relatório web com galerias de imagens, metadados, links diretos ao Google Maps e resumos de status.  
- **PDF Profissional:**  
  - Capa personalizável (logotipo, título, data e metadados gerais).  
  - Índices e Tabelas: resumo de quadras/canteiros com status agregados e contagens.  
  - Registros Detalhados: até 2 fotos por página, com comentários e metadados.  
  - Página de assinaturas: espaço para responsáveis assinarem.  
  - Integração com Questionário de Poda: injeta respostas no relatório com estilo uniforme.

### 3. Editor de Configurações
- Interface para editar cabeçalhos, rodapés, títulos de seções e estilos de capa.  
- Pré-visualização em tempo real das alterações antes de salvar.

### 4. Macros de Comentários
- Criação e gerenciamento de atalhos de texto (ex.: clicar no nome da imagem + digitar número = Texto salvo em req_classes/macros.json).  
- Acelera a digitação de observações repetitivas.

### 5. PintaQuadra
- Ferramenta de desenho para colorir polígonos de quadras/canteiros no mapa original.  
- Exportação de mapa com legenda indicando status de cada unidade.

### 6. Persistência de Dados
- Banco de dados leve em formato JSON:  
  - Histórico de imagens processadas e seus estados.  
  - Comentários e respostas ao questionário.  
  - Configurações do usuário e modelos de relatório.
  - Estados do PintaQuadra.



