// Copyright (c) Microsoft. All rights reserved.

// Ressources applicatives (portee resource group), invoquees par
// `main.bicep`. Provisionne l'architecture decrite par CLAUDE.md "Stack
// technique" : Azure OpenAI (2 deploiements), Azure AI Search (RAG), Cosmos
// DB (persistance, src/tools/persistence.py), Container Apps (API + UI,
// Dockerfile), Container Registry, identite managee, Log Analytics +
// Application Insights.
//
// Azure OpenAI est provisionne en `kind: 'AIServices'` avec
// `allowProjectManagement: true` (upgrade non destructif d'un compte
// `kind: 'OpenAI'`, DECISIONS.md #25) et expose un sous-projet Microsoft
// Foundry (`accounts/projects`) : une fois connecte a `appInsights` (etape
// manuelle, docs/deployment.md #8.12), l'orchestration `WorkflowBuilder`
// (src/orchestrator/graph.py) est tracee dans Observability > Traces du
// projet Foundry (ai.azure.com).
//
// Aucun secret en clair : l'identite managee du Container App s'authentifie
// auprès d'ACR / Azure OpenAI / Azure AI Search / Cosmos DB via des role
// assignments Microsoft Entra ID (`disableLocalAuth: true` sur Azure OpenAI
// et Cosmos DB desactive completement les cles API/maitre).

@description('Region Azure de toutes les ressources.')
param location string

@minLength(4)
@description('Suffixe court et unique utilise pour deriver les noms de ressources.')
param resourceToken string

@description('Tags appliques a toutes les ressources.')
param tags object

@description('Object ID du principal azd (developpement local), optionnel.')
param principalId string = ''

@description('Type du principal azd ci-dessus (Cloud Shell / utilisateurs : User ; pipelines CI : ServicePrincipal).')
@allowed(['User', 'ServicePrincipal', 'Group'])
param principalType string = 'User'

@description('Nom du deploiement Azure OpenAI "fort" (agent RootCause). Doit correspondre a AZURE_OPENAI_CHAT_DEPLOYMENT.')
param chatDeploymentName string = 'gpt-4o'

@description('Nom du deploiement Azure OpenAI "leger" (extraction, KB search, summary, ...). Doit correspondre a AZURE_OPENAI_CHAT_DEPLOYMENT_LIGHT.')
param chatDeploymentLightName string = 'gpt-4o-mini'

@description('Version de l\'API Azure OpenAI utilisee par le client (src/config.py).')
param openAiApiVersion string = '2024-10-21'

// --- Roles RBAC integres (GUIDs constants, communs a tous les tenants Azure) --

var acrPullRoleId = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '7f951dda-4ed3-4680-a7ca-43fe172d538d')
var cognitiveServicesOpenAiUserRoleId = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd')
var searchIndexDataReaderRoleId = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '1407120a-92aa-4202-b7e9-c0e197c71c8f')
var cosmosDataContributorRoleId = '00000000-0000-0000-0000-000000000002'

// --- Observabilite (Log Analytics + Application Insights) --------------------

resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2022-10-01' = {
  name: 'law-${resourceToken}'
  location: location
  tags: tags
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
  }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: 'appi-${resourceToken}'
  location: location
  tags: tags
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logAnalytics.id
    IngestionMode: 'LogAnalytics'
  }
}

// --- Identite managee (attachee au Container App) -----------------------------

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-${resourceToken}'
  location: location
  tags: tags
}

// --- Container Registry (image buildee/poussee par `azd deploy`) -------------

resource containerRegistry 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: 'acr${resourceToken}'
  location: location
  tags: tags
  sku: {
    name: 'Basic'
  }
  properties: {
    adminUserEnabled: false
  }
}

resource acrPullAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(containerRegistry.id, identity.id, acrPullRoleId)
  scope: containerRegistry
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: acrPullRoleId
  }
}

// --- Azure OpenAI (agents "fort"/"leger", src/agents/clients.py) -------------

// kind 'AIServices' + allowProjectManagement: true : upgrade non destructif
// depuis 'OpenAI' (endpoint/cles/RBAC/deploiements inchanges), expose le
// sous-projet Microsoft Foundry `foundryProject` ci-dessous (DECISIONS.md #25).
// identity SystemAssigned : requis par l'ARM provider pour
// `allowProjectManagement: true` (sans elle, `azd up` echoue sur
// `foundryProject` avec BadRequest "To create projects, you must enable a
// managed identity on your resource", DECISIONS.md #26).
resource openAi 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: 'aoai-${resourceToken}'
  location: location
  tags: tags
  kind: 'AIServices'
  sku: {
    name: 'S0'
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    customSubDomainName: 'aoai-${resourceToken}'
    disableLocalAuth: true
    allowProjectManagement: true
  }
}

// version 2024-11-20 : 2024-08-06 et 2024-05-13 sont depreciees pour les
// nouveaux deploiements (Azure OpenAI Model Retirement Schedule, oct. 2025).
resource openAiChatDeployment 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = {
  parent: openAi
  name: chatDeploymentName
  sku: {
    name: 'GlobalStandard'
    capacity: 10
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: 'gpt-4o'
      version: '2024-11-20'
    }
  }
}

// Azure OpenAI n'autorise pas deux operations de deploiement concurrentes sur
// le meme compte : `dependsOn` force la creation sequentielle (sinon ARM peut
// paralleliser et l'un des deux echoue avec un conflit).
resource openAiChatDeploymentLight 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = {
  parent: openAi
  name: chatDeploymentLightName
  sku: {
    name: 'GlobalStandard'
    capacity: 10
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: 'gpt-4o-mini'
      version: '2024-07-18'
    }
  }
  dependsOn: [
    openAiChatDeployment
  ]
}

resource openAiRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(openAi.id, identity.id, cognitiveServicesOpenAiUserRoleId)
  scope: openAi
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: cognitiveServicesOpenAiUserRoleId
  }
}

resource openAiRoleAssignmentDev 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(principalId)) {
  name: guid(openAi.id, principalId, cognitiveServicesOpenAiUserRoleId)
  scope: openAi
  properties: {
    principalId: principalId
    principalType: principalType
    roleDefinitionId: cognitiveServicesOpenAiUserRoleId
  }
}

// Projet Microsoft Foundry (ai.azure.com) : rend l'orchestration
// `WorkflowBuilder` visible dans Observability > Traces une fois connecte a
// `appInsights` (etape manuelle, docs/deployment.md #8.12, DECISIONS.md #25).
resource foundryProject 'Microsoft.CognitiveServices/accounts/projects@2025-06-01' = {
  parent: openAi
  name: 'proj-${resourceToken}'
  location: location
  properties: {
    displayName: 'Incident RCA Agents'
    description: 'Diagnostic multi-agents d\'un incident de paiement (CLAUDE.md) : orchestration WorkflowBuilder (LogAnalyzer -> IncidentExtractor -> KBSearch -> RootCause <-> GatherEvidence -> HumanApproval -> Remediation -> Summary).'
  }
}

// --- Azure AI Search (KB RAG, src/tools/knowledge_base.py KB_MODE=azure_search) --

resource search 'Microsoft.Search/searchServices@2023-11-01' = {
  name: 'srch-${resourceToken}'
  location: location
  tags: tags
  sku: {
    name: 'basic'
  }
  properties: {
    replicaCount: 1
    partitionCount: 1
  }
}

resource searchRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(search.id, identity.id, searchIndexDataReaderRoleId)
  scope: search
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: searchIndexDataReaderRoleId
  }
}

resource searchRoleAssignmentDev 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(principalId)) {
  name: guid(search.id, principalId, searchIndexDataReaderRoleId)
  scope: search
  properties: {
    principalId: principalId
    principalType: principalType
    roleDefinitionId: searchIndexDataReaderRoleId
  }
}

// --- Cosmos DB (persistance SharedContext, src/tools/persistence.py) ---------

resource cosmos 'Microsoft.DocumentDB/databaseAccounts@2024-08-15' = {
  name: 'cosmos-${resourceToken}'
  location: location
  tags: tags
  kind: 'GlobalDocumentDB'
  properties: {
    databaseAccountOfferType: 'Standard'
    consistencyPolicy: {
      defaultConsistencyLevel: 'Session'
    }
    locations: [
      {
        locationName: location
        failoverPriority: 0
      }
    ]
    capabilities: [
      {
        name: 'EnableServerless'
      }
    ]
    disableLocalAuth: true
  }
}

resource cosmosDatabase 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2024-08-15' = {
  parent: cosmos
  name: 'incidents'
  properties: {
    resource: {
      id: 'incidents'
    }
  }
}

resource cosmosContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-08-15' = {
  parent: cosmosDatabase
  name: 'records'
  properties: {
    resource: {
      id: 'records'
      partitionKey: {
        paths: ['/id']
        kind: 'Hash'
      }
    }
  }
}

// Role Cosmos DB integre "Built-in Data Contributor" (data-plane) : pas de
// sqlRoleDefinitions custom necessaire, on reference le role integre par GUID.
resource cosmosDataContributorAssignment 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-08-15' = {
  parent: cosmos
  name: guid(cosmos.id, identity.id, cosmosDataContributorRoleId)
  properties: {
    roleDefinitionId: '${cosmos.id}/sqlRoleDefinitions/${cosmosDataContributorRoleId}'
    principalId: identity.properties.principalId
    scope: cosmos.id
  }
}

resource cosmosDataContributorAssignmentDev 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-08-15' = if (!empty(principalId)) {
  parent: cosmos
  name: guid(cosmos.id, principalId, cosmosDataContributorRoleId)
  properties: {
    roleDefinitionId: '${cosmos.id}/sqlRoleDefinitions/${cosmosDataContributorRoleId}'
    principalId: principalId
    scope: cosmos.id
  }
}

// --- Container Apps (API + UI, Dockerfile) ------------------------------------

resource containerAppsEnvironment 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: 'cae-${resourceToken}'
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalytics.properties.customerId
        sharedKey: logAnalytics.listKeys().primarySharedKey
      }
    }
  }
}

// Image placeholder : `azd deploy` construit Dockerfile, le pousse sur
// `containerRegistry` et met a jour cette reference. minReplicas=maxReplicas=1
// : le registre des runs (`app.state.runs`, src/api/runs.py) est en memoire,
// plusieurs replicas casseraient la reprise HITL (DECISIONS.md #18).
resource containerApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: 'api-${resourceToken}'
  location: location
  tags: union(tags, { 'azd-service-name': 'api' })
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${identity.id}': {}
    }
  }
  properties: {
    managedEnvironmentId: containerAppsEnvironment.id
    configuration: {
      ingress: {
        external: true
        targetPort: 8000
        transport: 'auto'
      }
      registries: [
        {
          server: containerRegistry.properties.loginServer
          identity: identity.id
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'api'
          image: 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'
          env: [
            { name: 'AZURE_AUTH_MODE', value: 'managed_identity' }
            { name: 'AZURE_CLIENT_ID', value: identity.properties.clientId }
            { name: 'AZURE_OPENAI_ENDPOINT', value: openAi.properties.endpoint }
            { name: 'AZURE_OPENAI_CHAT_DEPLOYMENT', value: chatDeploymentName }
            { name: 'AZURE_OPENAI_CHAT_DEPLOYMENT_LIGHT', value: chatDeploymentLightName }
            { name: 'AZURE_OPENAI_API_VERSION', value: openAiApiVersion }
            { name: 'AZURE_AI_SEARCH_ENDPOINT', value: 'https://${search.name}.search.windows.net' }
            { name: 'AZURE_AI_SEARCH_INDEX', value: 'incident-kb' }
            { name: 'COSMOS_ENDPOINT', value: cosmos.properties.documentEndpoint }
            { name: 'COSMOS_DATABASE', value: 'incidents' }
            { name: 'COSMOS_CONTAINER', value: 'records' }
            { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsights.properties.ConnectionString }
          ]
          resources: {
            cpu: json('1.0')
            memory: '2.0Gi'
          }
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 1
      }
    }
  }
  dependsOn: [
    acrPullAssignment
  ]
}

// --- Sorties (main.bicep -> azd env -> `azd env get-values` pour un .env local) --

output AZURE_CONTAINER_REGISTRY_ENDPOINT string = containerRegistry.properties.loginServer

output AZURE_OPENAI_ENDPOINT string = openAi.properties.endpoint
output AZURE_OPENAI_CHAT_DEPLOYMENT string = chatDeploymentName
output AZURE_OPENAI_CHAT_DEPLOYMENT_LIGHT string = chatDeploymentLightName
output AZURE_OPENAI_API_VERSION string = openAiApiVersion

output AZURE_FOUNDRY_PROJECT_NAME string = foundryProject.name
output AZURE_FOUNDRY_PROJECT_ID string = foundryProject.id

output AZURE_AI_SEARCH_ENDPOINT string = 'https://${search.name}.search.windows.net'
output AZURE_AI_SEARCH_INDEX string = 'incident-kb'

output COSMOS_ENDPOINT string = cosmos.properties.documentEndpoint
output COSMOS_DATABASE string = 'incidents'
output COSMOS_CONTAINER string = 'records'

output APPLICATIONINSIGHTS_CONNECTION_STRING string = appInsights.properties.ConnectionString

output SERVICE_API_NAME string = containerApp.name
output SERVICE_API_URI string = 'https://${containerApp.properties.configuration.ingress.fqdn}'
