import type { ModelDescriptor, ModelProvider, ModelRequest, ModelResponse } from "../types/index.js";
import { ModelProviderError } from "../types/index.js";

/**
 * The Model Gateway (section 3): a provider-agnostic registry.
 *
 * Nothing else in test0 should import a concrete provider directly —
 * everything goes through this gateway, so adding a new model source is
 * just `gateway.registerProvider(new SomeProvider())`.
 */
export class ModelGateway {
  private providers = new Map<string, ModelProvider>();

  registerProvider(provider: ModelProvider): void {
    this.providers.set(provider.id, provider);
  }

  unregisterProvider(providerId: string): void {
    this.providers.delete(providerId);
  }

  listProviders(): ModelProvider[] {
    return [...this.providers.values()];
  }

  getProvider(providerId: string): ModelProvider | undefined {
    return this.providers.get(providerId);
  }

  async listAllModels(): Promise<ModelDescriptor[]> {
    const lists = await Promise.all(
      this.listProviders().map(async (p) => {
        try {
          return await p.listModels();
        } catch {
          return [];
        }
      })
    );
    return lists.flat();
  }

  async findModel(modelId: string): Promise<{ provider: ModelProvider; descriptor: ModelDescriptor } | undefined> {
    for (const provider of this.listProviders()) {
      const models = await provider.listModels();
      const descriptor = models.find((m) => m.id === modelId);
      if (descriptor) return { provider, descriptor };
    }
    return undefined;
  }

  async checkAvailability(providerId: string): Promise<boolean> {
    const provider = this.providers.get(providerId);
    if (!provider) return false;
    try {
      return await provider.checkAvailability();
    } catch {
      return false;
    }
  }

  /** Execute against a specific model id, surfacing a normalized error on failure. */
  async complete(modelId: string, request: ModelRequest): Promise<ModelResponse> {
    const found = await this.findModel(modelId);
    if (!found) {
      throw new ModelProviderError(`No provider exposes model "${modelId}"`, "gateway", "unknown");
    }
    return found.provider.complete(modelId, request);
  }
}
