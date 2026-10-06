/** Preserve the data source's row type at Element Plus table slot boundaries. */
type TableRow<T> = import('vue').UnwrapRef<T> extends readonly (infer Row)[] ? Row : never
