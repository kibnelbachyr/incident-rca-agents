// Copyright (c) Microsoft. All rights reserved.

// Point d'entree azd (`azd up` / `azd provision`), portee abonnement : cree le
// groupe de ressources de l'environnement puis delegue le provisionnement des
// ressources applicatives a `resources.bicep` (DECISIONS.md #21).

targetScope = 'subscription'

@minLength(1)
@maxLength(64)
@description('Nom de l\'environnement azd, utilise pour deriver les noms de ressources.')
param environmentName string

@minLength(1)
@description('Region Azure de toutes les ressources. Choisir une region avec deploiements GPT-4o / GPT-4o-mini "GlobalStandard" disponibles (ex: swedencentral, eastus2).')
param location string

@description('Object ID du principal azd (developpement local), pour lui accorder les roles data-plane (Azure OpenAI, AI Search, Cosmos DB).')
param principalId string = ''

var tags = {
  'azd-env-name': environmentName
}

var resourceToken = toLower(uniqueString(subscription().id, environmentName, location))

resource rg 'Microsoft.Resources/resourceGroups@2021-04-01' = {
  name: 'rg-${environmentName}'
  location: location
  tags: tags
}

module resources 'resources.bicep' = {
  name: 'resources'
  scope: rg
  params: {
    location: location
    resourceToken: resourceToken
    tags: tags
    principalId: principalId
  }
}

output AZURE_LOCATION string = location
output AZURE_RESOURCE_GROUP string = rg.name
output AZURE_TENANT_ID string = tenant().tenantId

output AZURE_CONTAINER_REGISTRY_ENDPOINT string = resources.outputs.AZURE_CONTAINER_REGISTRY_ENDPOINT

// Variables d'environnement de l'application (mappent 1:1 sur src/config.py
// Settings) : utilisables localement via `azd env get-values` pour faire
// tourner l'API hors conteneur contre les vraies ressources Azure.
output AZURE_OPENAI_ENDPOINT string = resources.outputs.AZURE_OPENAI_ENDPOINT
output AZURE_OPENAI_CHAT_DEPLOYMENT string = resources.outputs.AZURE_OPENAI_CHAT_DEPLOYMENT
output AZURE_OPENAI_CHAT_DEPLOYMENT_LIGHT string = resources.outputs.AZURE_OPENAI_CHAT_DEPLOYMENT_LIGHT
output AZURE_OPENAI_API_VERSION string = resources.outputs.AZURE_OPENAI_API_VERSION

output AZURE_FOUNDRY_PROJECT_NAME string = resources.outputs.AZURE_FOUNDRY_PROJECT_NAME
output AZURE_FOUNDRY_PROJECT_ID string = resources.outputs.AZURE_FOUNDRY_PROJECT_ID
output AZURE_FOUNDRY_PROJECT_ENDPOINT string = resources.outputs.AZURE_FOUNDRY_PROJECT_ENDPOINT

output AZURE_AI_SEARCH_ENDPOINT string = resources.outputs.AZURE_AI_SEARCH_ENDPOINT
output AZURE_AI_SEARCH_INDEX string = resources.outputs.AZURE_AI_SEARCH_INDEX

output COSMOS_ENDPOINT string = resources.outputs.COSMOS_ENDPOINT
output COSMOS_DATABASE string = resources.outputs.COSMOS_DATABASE
output COSMOS_CONTAINER string = resources.outputs.COSMOS_CONTAINER

output APPLICATIONINSIGHTS_CONNECTION_STRING string = resources.outputs.APPLICATIONINSIGHTS_CONNECTION_STRING

output SERVICE_API_NAME string = resources.outputs.SERVICE_API_NAME
output SERVICE_API_URI string = resources.outputs.SERVICE_API_URI
